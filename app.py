from datetime import datetime, timedelta, timezone
from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
from utils import convert_currency, fetchCharts, getIntervalFromRange, getPortfolioDoc, getPortfolioDocRef, getPortfolioStocksValuesUsingQuantity, fetchQuoteStocks, getReferenceCurrency
import firebase_admin
from firebase_admin import credentials, firestore
from cache import cache
from dotenv import load_dotenv
import os
import logging
from logging.handlers import RotatingFileHandler
from functools import wraps

# Load environment variables
load_dotenv(".env")

# Configure logging
def setup_logging(app):
    """Configure application logging"""
    if not app.debug:
        # Create logs directory if it doesn't exist
        if not os.path.exists('logs'):
            os.mkdir('logs')
        
        # File handler for errors
        file_handler = RotatingFileHandler(
            'logs/portfolio_api.log',
            maxBytes=10485760,  # 10MB
            backupCount=10
        )
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
        ))
        file_handler.setLevel(logging.INFO)
        app.logger.addHandler(file_handler)
        
        app.logger.setLevel(logging.INFO)
        app.logger.info('Portfolio API startup')

app = Flask(__name__)

# Security headers
@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response

# CORS configuration
CORS(app, resources={
    r"/*": {
        "origins": os.getenv('ALLOWED_ORIGINS', '*').split(','),
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"]
    }
})

# Cache configuration
cache.init_app(app, config={
    'CACHE_TYPE': 'SimpleCache',
    'CACHE_DEFAULT_TIMEOUT': 900
})

# Firebase initialization with error handling
firebase_creds = {
    "type": os.getenv('FIREBASE_TYPE'),
    "project_id": os.getenv('FIREBASE_PROJECT_ID'),
    "private_key_id": os.getenv('FIREBASE_PRIVATE_KEY_ID'),
    "private_key": os.getenv('FIREBASE_PRIVATE_KEY').replace('\\n', '\n'),
    "client_email": os.getenv('FIREBASE_CLIENT_EMAIL'),
    "client_id": os.getenv('FIREBASE_CLIENT_ID'),
    "auth_uri": os.getenv('FIREBASE_AUTH_URI'),
    "token_uri": os.getenv('FIREBASE_TOKEN_URI'),
    "auth_provider_x509_cert_url": os.getenv('FIREBASE_AUTH_PROVIDER_CERT_URL'),
    "client_x509_cert_url": os.getenv('FIREBASE_CLIENT_CERT_URL'),
    "universe_domain": os.getenv('FIREBASE_UNIVERSE_DOMAIN')
}

cred = credentials.Certificate(firebase_creds)
firebase_admin.initialize_app(cred)
db = firestore.client()

# Get API config from environment
API_URL = os.getenv('API_URL')
API_HEADERS = {
    'X-API-KEY': os.getenv('API_KEY')
}

# Error handlers
@app.errorhandler(400)
def bad_request(error):
    return jsonify({"error": "Bad request", "message": str(error)}), 400

@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Resource not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    app.logger.error(f"Internal error: {error}")
    return jsonify({"error": "Internal server error"}), 500

@app.errorhandler(Exception)
def handle_exception(e):
    app.logger.error(f"Unhandled exception: {e}", exc_info=True)
    return jsonify({"error": "An unexpected error occurred"}), 500

# Request validation decorator
def validate_owner_id(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        owner_id = request.args.get("owner_id")
        if not owner_id:
            return jsonify({"error": "Missing owner_id parameter"}), 400
        return f(*args, **kwargs)
    return decorated_function

# Health check endpoint
@app.route('/health')
def health_check():
    """Health check endpoint for load balancers"""
    try:
        # Check database connection
        db.collection('_health_check').limit(1).get()
        
        return jsonify({
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": "1.0.0"
        }), 200
    except Exception as e:
        app.logger.error(f"Health check failed: {e}")
        return jsonify({
            "status": "unhealthy",
            "error": str(e)
        }), 503

@app.route('/ready')
def readiness_check():
    """Readiness check endpoint"""
    return jsonify({"status": "ready"}), 200

# API Routes
@app.route('/marketSummary/<region>')
def getMarketSummary(region):
    owner_id = request.args.get("owner_id")

    trending_response = requests.get(f"{API_URL}/v1/finance/trending/{region}", headers=API_HEADERS)
    trending_data = trending_response.json()

    if "finance" not in trending_data or not trending_data["finance"]["result"]:
        return jsonify([])

    symbols = [quote["symbol"] for quote in trending_data["finance"]["result"][0]["quotes"]]
    symbols_str = ",".join(symbols[:10])

    filtered_stocks = fetchQuoteStocks(symbols_str)

    reference_currency = getReferenceCurrency(db, owner_id)
    if reference_currency != "USD":
        for stock in filtered_stocks:
            if "price" in stock:
                stock["price"] = convert_currency(stock["price"], "USD", reference_currency)
            stock["currency"] = reference_currency

    return jsonify(filtered_stocks)

@app.route('/portfolio/stocks/chart')
@validate_owner_id
def getPortfolioStocksCharts():
    owner_id = request.args.get("owner_id")
    
    if not owner_id:
        return jsonify({"error": "Missing owner_id"}), 400

    reference_currency = getReferenceCurrency(db, owner_id)
    doc = getPortfolioDoc(db, owner_id)
    if not doc:
        return jsonify([])

    stocks = doc.get("stocks", {})
    if not stocks:
        return jsonify([])

    symbols_str = ",".join(stocks.keys())
    range_param = request.args.get('range', "1d")
    interval = getIntervalFromRange(range_param)

    charts = fetchCharts(symbols_str, interval, range_param)

    if reference_currency != "USD":
        for symbol, data in charts.items():
            for key in ['close', 'open', 'high', 'low']:
                if key in data:
                    data[key] = [convert_currency(price, 'USD', reference_currency) for price in data[key]]
            if 'chartPreviousClose' in data:
                data['chartPreviousClose'] = convert_currency(data['chartPreviousClose'], 'USD', reference_currency)
            data['currency'] = reference_currency

    response = []
    for symbol, data in charts.items():
        timestamps = data.get("timestamp", [])
        close_prices = data.get("close", [])

        date_strings = [datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S") for ts in timestamps]

        response.append({
            "symbol": symbol,
            "date": date_strings,
            "close": close_prices
        })

    print(response)
    return jsonify(response)

@app.route('/portfolio/value/chart')
@validate_owner_id
@app.route('/portfolio/value/chart')
def getPortfolioChart():
    owner_id = request.args.get("owner_id")
    range_filter = request.args.get("range", "1w")

    if not owner_id:
        return jsonify({"error": "Missing owner_id"}), 400

    reference_currency = getReferenceCurrency(db, owner_id)
    doc = getPortfolioDoc(db, owner_id)
    if not doc:
        return jsonify({"history": {}})

    timesAndValues = doc.get("history", {})

    history_filtered = {}
    today = datetime.now(timezone.utc).date()

    if range_filter == "1w":
        start_date = today - timedelta(weeks=1)
    elif range_filter == "1mo":
        start_date = today - timedelta(days=30)
    elif range_filter == "3mo":
        start_date = today - timedelta(days=90)
    else:
        start_date = None 

    for date_str, value in timesAndValues.items():
        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
        if start_date is None or date_obj >= start_date:
            history_filtered[date_str] = value

    if reference_currency != "USD":
        converted_history = {}
        for date, value in history_filtered.items():
            converted_history[date] = convert_currency(value, 'USD', reference_currency)
        return jsonify({"history": converted_history})

    return jsonify({"history": history_filtered})

@app.route('/portfolio/value')
@validate_owner_id
def getPortfolioValue():
    owner_id = request.args.get("owner_id")
    
    if not owner_id:
        return jsonify({"error": "Missing owner_id"}), 400
    
    reference_currency = getReferenceCurrency(db, owner_id)
    doc=getPortfolioDoc(db, owner_id)
    if not doc:
        return {}
    
    stocks = doc.get("stocks", {})
    stocks_count = len(stocks)
    today = datetime.now()
    yesterday = today - timedelta(days=1)
    today_str = today.strftime("%Y-%m-%d")
    yesterday_str = yesterday.strftime("%Y-%m-%d")
    history = doc.get("history", {})
    yesterday_history_value = history.get(yesterday_str, 0)
    today_history_value = history.get(today_str, 0)

    if today_history_value == 0 and stocks:
        symbols_str = ",".join(stocks.keys())
        try:
            stock_data = fetchQuoteStocks(symbols_str)
            for stock in stock_data:
                symbol = stock['symbol']
                current_price = stock['price']  # USD
                quantity = stocks.get(symbol, 0)
                today_history_value += current_price * quantity
            docRef = getPortfolioDocRef(db, owner_id)
            docRef.update({f"history.{today_str}": today_history_value})
        except Exception as e:
            print(f"Error calculating today's value: {e}")

    if yesterday_history_value == 0:
        change_percentage = "0.00%"
        change = 0
    else:
        change = (today_history_value - yesterday_history_value)
        change_percentage = f"{((change / yesterday_history_value) * 100):+.2f}%"

    converted_value = convert_currency(today_history_value, 'USD', reference_currency)
    converted_change = convert_currency(change, 'USD', reference_currency)

    return jsonify({
        "portfolioValue": converted_value,
        "stocks": stocks_count,
        "changePercentage": change_percentage,
        "change": converted_change,
        "currency": reference_currency
    })

@app.route('/portfolio/stocks/values')
@validate_owner_id
def getPortfolioStocksValues():
    owner_id = request.args.get("owner_id")
    
    if not owner_id:
        return jsonify({"error": "Missing owner_id"}), 400

    reference_currency = getReferenceCurrency(db, owner_id)
    doc=getPortfolioDoc(db, owner_id)
    if not doc:
        return {}
    stocksAndQuantities = doc.get("stocks")
    symbols_str = ",".join(stocksAndQuantities.keys())
    data = getPortfolioStocksValuesUsingQuantity(symbols_str, stocksAndQuantities)
    
    # Convert values to requested currency
    if reference_currency != "USD":
        for stock in data:
            if 'value' in stock:
                stock['value'] = convert_currency(stock['value'], 'USD', reference_currency)
            if 'price' in stock:
                stock['price'] = convert_currency(stock['price'], 'USD', reference_currency)
            stock['currency'] = reference_currency


    return jsonify(data)

@app.route('/portfolio/stocks/distribution')
@validate_owner_id
def getPortfolioStocksDistribution():
    owner_id = request.args.get("owner_id")
    if not owner_id:
        return jsonify({"error": "Missing owner_id"}), 400
    doc=getPortfolioDoc(db, owner_id)
    if not doc:
        return {}
    stocksAndQuantities = doc.get("stocks")
    symbols_str = ",".join(stocksAndQuantities.keys())
    data = getPortfolioStocksValuesUsingQuantity(symbols_str, stocksAndQuantities)
    today = datetime.now()
    today_str = today.strftime("%Y-%m-%d")
    valuePortfolio = doc.get("history").get(today_str, 0)

    response = []
    for d in data:
        response.append({"symbol": d['symbol'], "value": f"{d['value'] / valuePortfolio * 100}"})

    return jsonify(response)

@app.route('/portfolio/stocks')
@validate_owner_id
def getPortfolioStocks():
    owner_id = request.args.get("owner_id")
    
    if not owner_id:
        return jsonify({"error": "Missing owner_id"}), 400

    reference_currency = getReferenceCurrency(db, owner_id)
    doc=getPortfolioDoc(db, owner_id)
    if not doc:
        return []
    stocksAndQuantities = doc.get("stocks")
    if(not stocksAndQuantities):
       return []
    symbols_str = ",".join(stocksAndQuantities.keys())
    
    def fetch_data(symbols_str, interval, range):
        return fetchCharts(symbols_str, interval, range)
    
    data = fetch_data(symbols_str, "1d", "1d")
    response = []
    
    for symbol, d in data.items():
        current_price = d['close'][0]
        prev_close = d['chartPreviousClose']
        change_percent = ((current_price - prev_close) / prev_close) * 100
        change_str = f"{change_percent:+.2f}%"

        converted_price = convert_currency(current_price * stocksAndQuantities[symbol], 'USD', reference_currency)
        
        response.append({
            "symbol": symbol,
            "quantity": f"{stocksAndQuantities[symbol]} stocks",
            "price": converted_price,
            "change": change_str,
            "currency": reference_currency
        })
    return jsonify(response)

@app.route('/portfolio/overview')
@validate_owner_id
def getPortfolioOverview():
    owner_id = request.args.get("owner_id")
    
    if not owner_id:
        return jsonify({"error": "Missing owner_id"}), 400
    reference_currency = getReferenceCurrency(db, owner_id)
    doc=getPortfolioDoc(db, owner_id)
    if not doc:
        print("No document found!")
        return {}
    
    cost = doc.get("cost", 0)
    history = doc.get("history", {})
    stocks = doc.get("stocks", {})
    today_str = datetime.now().strftime("%Y-%m-%d")

    value = 0
    if stocks:
        symbols_str = ",".join(stocks.keys())
        try:
            stock_data = fetchQuoteStocks(symbols_str)
            
            for stock in stock_data:
                symbol = stock['symbol']
                current_price = stock['price']  # USD
                quantity = stocks.get(symbol, 0)
                stock_value = current_price * quantity
                value += stock_value

            if today_str not in history or history[today_str] == 0:
                docRef = getPortfolioDocRef(db, owner_id)
                docRef.update({f"history.{today_str}": value})
        except Exception as e:
            print(f"Error calculating portfolio value: {e}")
            if today_str in history:
                value = history[today_str]
            elif history:
                last_date_str = max(history.keys(), key=lambda d: datetime.strptime(d, "%Y-%m-%d"))
                value = history[last_date_str]
    
    number_of_stocks = 0
    for s in stocks.values():
        number_of_stocks += s

    change_percentage = ((value - cost) / cost * 100) if cost != 0 else 0
    profit = value - cost

    converted_cost = convert_currency(cost, 'USD', reference_currency)
    converted_value = convert_currency(value, 'USD', reference_currency)
    converted_profit = convert_currency(profit, 'USD', reference_currency)
    
    result = {
        "cost": converted_cost,
        "value": converted_value,
        "profit": converted_profit,
        "change": change_percentage,
        "numberOfStocks": number_of_stocks,
        "currency": reference_currency
    }
    return jsonify(result)
    
@app.route('/portfolio/sell', methods=['POST'])
@validate_owner_id
def sellStock():
    try:
        owner_id = request.args.get("owner_id")
        
        if not owner_id:
            return jsonify({"error": "Missing owner_id"}), 400
        
        reference_currency = getReferenceCurrency(db, owner_id)

        doc = getPortfolioDocRef(db, owner_id)
        doc_data = doc.get()

        if not doc_data.exists:
            return jsonify({"error": "Portfolio not found. Please buy stocks first."}), 404

        data = request.get_json()        
        if not data:
            return jsonify({"error": "Invalid JSON data"}), 400

        symbol = data.get("symbol")
        quantity = data.get("quantity")

        if not symbol or not quantity or quantity <= 0:
            return jsonify({"error": "Missing or invalid symbol or quantity"}), 400

        docData = doc_data.to_dict()
        ownedQuantity = docData.get("stocks", {}).get(symbol, 0)

        if ownedQuantity < quantity:
            return jsonify({"error": "Not enough stocks to sell"}), 400

        response = fetchQuoteStocks(symbol)       
        if not response or not response[0]:
            return jsonify({"error": "Invalid stock symbol"}), 400

        price = response[0]['price'] 
        history = docData.get("history", {})
        today_str = datetime.now().strftime("%Y-%m-%d")
        yesterdayValueNotAdded = 0

        if today_str not in history and history:
            last_date_str = max(history.keys(), key=lambda d: datetime.strptime(d, "%Y-%m-%d"))
            yesterdayValueNotAdded = history[last_date_str]

        stocks = docData.get("stocks", {})
        total_stocks_remaining = sum(stocks.values()) - quantity

        if ownedQuantity == quantity:
            if total_stocks_remaining == 0:
                doc.update({
                    f"stocks.{symbol}": firestore.DELETE_FIELD,
                    "cost": 0,
                    f"history.{today_str}": 0
                })
            else:
                doc.update({
                    f"stocks.{symbol}": firestore.DELETE_FIELD,
                    "cost": firestore.Increment(price * quantity * -1),
                    f"history.{today_str}": firestore.Increment(price * quantity * -1 + yesterdayValueNotAdded)
                })
        else:
            doc.update({
                f"stocks.{symbol}": firestore.Increment(-quantity),
                "cost": firestore.Increment(price * quantity * -1),
                f"history.{today_str}": firestore.Increment(price * quantity * -1 + yesterdayValueNotAdded)
            })

        return jsonify({
            "message": "Stock sold successfully",
            "price": convert_currency(price * quantity, 'USD', reference_currency),
            "currency": reference_currency
        })
    except Exception as e:
        app.logger.error(f"Error in sellStock: {e}")
        return jsonify({"error": "Failed to sell stock"}), 500
 
@app.route('/portfolio/buy', methods=['POST'])
@validate_owner_id
def buyStock():
    owner_id = request.args.get("owner_id")
    
    if not owner_id:
        return jsonify({"error": "Missing owner_id"}), 400
    
    reference_currency = getReferenceCurrency(db, owner_id)
    
    doc = getPortfolioDocRef(db, owner_id)
    
    if not doc:
        return jsonify({"error": "Could not get portfolio"}), 500

    doc_data = doc.get()
    if not doc_data.exists:
        # Initialize portfolio if it doesn't exist
        doc.set({
            "stocks": {},
            "cost": 0,
            "history": {}
        })
        doc_data = doc.get()
    
    docData = doc_data.to_dict()
    
    data = request.get_json()
    
    if not data:
        return jsonify({"error": "Invalid JSON data"}), 400
    
    symbol = data.get("symbol")
    quantity = data.get("quantity")
    
    if not symbol or not quantity:
        return jsonify({"error": "Missing symbol or quantity"}), 400
    
    if quantity <= 0:
        return jsonify({"error": "Quantity must be greater than 0"}), 400
    
    response = fetchQuoteStocks(symbol)
    
    if not response or not response[0]:
        return jsonify({"error": "Wrong stock"}), 400

    price = response[0]['price']
    
    history = docData.get("history", {})
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    # Calculate the value to add to today's history
    yesterdayValueNotAdded = 0
    if today_str not in history:
        if history:
            # Get the most recent history value
            last_date_str = max(history.keys(), key=lambda d: datetime.strptime(d, "%Y-%m-%d"))
            yesterdayValueNotAdded = history[last_date_str]
            print(f"Yesterday's value to add: {yesterdayValueNotAdded} from {last_date_str}")
        else:
            print("No history found, starting fresh")
    else:
        print(f"Today already has history value: {history[today_str]}")
    
    stock_value = price * quantity
    history_increment = stock_value + yesterdayValueNotAdded

    doc.update({
        f"stocks.{symbol}": firestore.Increment(quantity),
        "cost": firestore.Increment(stock_value),
        f"history.{today_str}": firestore.Increment(history_increment)
    })

    converted_price = convert_currency(stock_value, 'USD', reference_currency)

    return jsonify({
        "message": "Stock bought successfully",
        "price": converted_price,
        "currency": reference_currency
    })

# Setup logging
setup_logging(app)

if __name__ == "__main__":
    # Only for development

    app.run(debug=False, host="0.0.0.0", port=5000)


