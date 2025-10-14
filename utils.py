import requests
from dotenv import load_dotenv
import os
from cache import cache
from freecurrencyapi import Client
import yfinance as yf

load_dotenv(".env")

API_URL = os.getenv('API_URL')
API_HEADERS = {
    'X-API-KEY': os.getenv('API_KEY')
}

# Initialize currency API client
currency_api_key = os.getenv('CURRENCY_EXCHNAGE')
currency_client = Client(currency_api_key)

# Get API config from environment
API_URL = os.getenv('API_URL')
API_HEADERS = {
    'X-API-KEY': os.getenv('API_KEY')
}

# Fallback exchange rates (updated periodically as backup)
FALLBACK_RATES = {
    'EUR': 0.92,
    'GBP': 0.79,
    'JPY': 149.50,
    'CAD': 1.36,
    'AUD': 1.52,
    'CHF': 0.88,
    'CNY': 7.24,
    'INR': 83.12,
    'MXN': 17.08,
    'BRL': 4.97,
    'ZAR': 18.65,
    'KRW': 1319.50,
    'SGD': 1.34,
    'NZD': 1.65,
    'SEK': 10.37,
    'NOK': 10.68,
    'DKK': 6.87,
    'PLN': 3.95,
    'THB': 34.82,
    'MYR': 4.47
}

# Store available currencies
SUPPORTED_CURRENCIES = list(FALLBACK_RATES.keys())

# @cache.memoize()
# def fetchQuoteStocks(symbols_str):
#     def refineStocks(trendingStocksWithData):
#         filtered_stocks = []
#         for quote in trendingStocksWithData.get("quoteResponse", {}).get("result", []):
#             filtered_stocks.append({
#                 "symbol": quote.get("symbol"),
#                 "shortName": quote.get("shortName") or quote.get("longName") or quote.get("symbol"),
#                 "price": quote.get("regularMarketPrice"),
#                 "change": round(quote.get("regularMarketChangePercent"),2)
#             })
#         return filtered_stocks
#     quotesQuerystring = {"symbols": symbols_str}
#     trendingStocksWithDataResponse = requests.request("GET", API_URL + "/v6/finance/quote", headers=API_HEADERS, params=quotesQuerystring)
#     trendingStocksWithData = trendingStocksWithDataResponse.json()
#     filtered_stocks = refineStocks(trendingStocksWithData)
#     return filtered_stocks

@cache.memoize()
def fetchQuoteStocks(symbols_str):
    print(f"\n--- fetchQuoteStocks called with: {symbols_str} ---")
    
    symbols = symbols_str.split(',')
    filtered_stocks = []
    
    for symbol in symbols:
        symbol = symbol.strip()
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            
            stock_data = {
                "symbol": symbol,
                "shortName": info.get("shortName", symbol),
                "price": info.get("currentPrice") or info.get("regularMarketPrice"),
                "change": round(info.get("regularMarketChangePercent", 0), 2)
            }
            
            if stock_data["price"]:
                filtered_stocks.append(stock_data)
                print(f"Fetched: {stock_data}")
        except Exception as e:
            print(f"Error fetching {symbol}: {e}")
            continue
    
    return filtered_stocks

@cache.memoize()
def fetchCharts(symbols_str, interval, range):
    querystring = {"symbols": symbols_str, "range": range, "interval": interval}
    chartsResponse = requests.request("GET", f"{API_URL}/v8/finance/spark", headers=API_HEADERS, params=querystring)
    charts = chartsResponse.json()
    return charts

def getIntervalFromRange(range):
    if range == "1d":
        return "1h"
    elif range == "5d":
        return "1d"
    elif range == "1mo":
        return "5d"
    else:
        return "1d"
    
def getPortfolioDoc(db, owner_id):
    doc_ref = db.collection("portfolio").document(owner_id)
    doc = doc_ref.get()
    if not doc.exists:
        return {}
    data = doc.to_dict()
    return data

def getReferenceCurrency(db, owner_id):
    doc_ref = db.collection("userInfo").document(owner_id)
    doc = doc_ref.get()
    if not doc.exists:
        return {}
    data = doc.to_dict()
    return data.get("referenceCurrency")

def getPortfolioDocRef(db, owner_id):
    doc_ref = db.collection("portfolio").document(owner_id)
    return doc_ref

def getPortfolioStocksValuesUsingQuantity(symbols_str, stocksAndQuantities):
    def fetch_data(symbols_str):
        return fetchQuoteStocks(symbols_str)
    stocks = fetch_data(symbols_str)
    response = []
    for s in stocks:
        stockToAppend = {"symbol": s['symbol'], "value": s['price'] * stocksAndQuantities[s['symbol']]}
        response.append(stockToAppend)
    return response

@cache.cached(timeout=3600, key_prefix='exchange_rates')
def get_exchange_rates():
    """
    Get all exchange rates with USD as base currency using currencies endpoint.
    Cached for 1 hour to reduce API calls.
    """
    try:
        response = currency_client.currencies(currencies=SUPPORTED_CURRENCIES)
        
        if response and 'data' in response:
            rates_response = currency_client.latest(base_currency='USD', currencies=SUPPORTED_CURRENCIES)
            rates = rates_response.get('data', {})
            
            if rates:
                print("Successfully fetched exchange rates from API")
                return rates
            else:
                print("Empty response from currency API, using fallback rates")
                return FALLBACK_RATES.copy()
        else:
            print("Invalid response from currency API, using fallback rates")
            return FALLBACK_RATES.copy()
    except Exception as e:
        print(f"Error fetching exchange rates: {e}")
        print("Using fallback exchange rates")
        return FALLBACK_RATES.copy()

def get_exchange_rate(from_currency='USD', to_currency='USD'):
    """
    Get exchange rate from one currency to another.
    """
    if not to_currency or to_currency.strip() == '':
        to_currency = 'USD'
    if not from_currency or from_currency.strip() == '':
        from_currency = 'USD'
    
    # Normalize to uppercase
    to_currency = to_currency.strip().upper()
    from_currency = from_currency.strip().upper()
    
    if from_currency == to_currency:
        return 1.0
    
    try:
        rates = get_exchange_rates()
        
        if to_currency not in rates:
            print(f"Currency {to_currency} not found in rates, checking fallback")
            if to_currency in FALLBACK_RATES:
                return FALLBACK_RATES[to_currency]
            else:
                print(f"Currency {to_currency} not supported, returning 1.0")
                return 1.0
        
        return rates.get(to_currency, 1.0)
    except Exception as e:
        print(f"Error getting exchange rate: {e}")
        return FALLBACK_RATES.get(to_currency, 1.0)

def convert_currency(amount, from_currency='USD', to_currency='USD'):
    """
    Convert amount from one currency to another.
    Returns original amount if conversion fails.
    """
    if not to_currency or to_currency.strip() == '':
        to_currency = 'USD'
    if not from_currency or from_currency.strip() == '':
        from_currency = 'USD'
    
    to_currency = to_currency.strip().upper()
    from_currency = from_currency.strip().upper()
    
    if from_currency == to_currency or amount == 0:
        return round(amount, 2)
    
    try:
        rate = get_exchange_rate(from_currency, to_currency)
        return round(amount * rate, 2)
    except Exception as e:
        print(f"Error converting currency: {e}")
        return round(amount, 2)
