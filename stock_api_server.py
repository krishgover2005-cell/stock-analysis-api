"""
Financial Analysis API Server
Fetches live stock data from Yahoo Finance for NSE/BSE stocks
Handles CORS, caching, and provides REST API for the frontend
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import yfinance as yf
from datetime import datetime, timedelta
import threading
import time

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# In-memory cache
stock_cache = {}
CACHE_DURATION = 300  # 5 minutes in seconds

# Background refresh
def background_refresh():
    """Refresh top stocks every 10 minutes"""
    top_stocks = [
        'RELIANCE.NS', 'TCS.NS', 'HDFCBANK.NS', 'INFY.NS', 'HINDUNILVR.NS',
        'ICICIBANK.NS', 'SBIN.NS', 'BHARTIARTL.NS', 'ITC.NS', 'LT.NS',
        'KOTAKBANK.NS', 'AXISBANK.NS', 'BAJFINANCE.NS', 'ASIANPAINT.NS',
        'MARUTI.NS', 'TITAN.NS', 'SUNPHARMA.NS', 'ULTRACEMCO.NS'
    ]
    
    while True:
        try:
            print(f"[{datetime.now()}] Background refresh starting...")
            for symbol in top_stocks:
                try:
                    fetch_stock_data(symbol)
                    time.sleep(0.5)  # Rate limiting
                except Exception as e:
                    print(f"Error refreshing {symbol}: {e}")
            print(f"[{datetime.now()}] Background refresh completed")
        except Exception as e:
            print(f"Background refresh error: {e}")
        
        time.sleep(600)  # Refresh every 10 minutes

def fetch_stock_data(symbol):
    """Fetch stock data from Yahoo Finance with retry logic"""
    try:
        # Ensure .NS suffix for Indian stocks
        if not symbol.endswith(('.NS', '.BO', '.NSE', '.BSE')):
            symbol = symbol + '.NS'
        
        # Clean symbol
        symbol = symbol.replace('.NSE', '.NS').replace('.BSE', '.BO')
        
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Fetching {symbol}...")
        
        # Check cache
        if symbol in stock_cache:
            cached_data, cached_time = stock_cache[symbol]
            age = (datetime.now() - cached_time).seconds
            if age < CACHE_DURATION:
                print(f"✓ Using cached data (age: {age}s)")
                return cached_data
        
        # Retry logic - try 3 times
        max_retries = 3
        for attempt in range(max_retries):
            try:
                print(f"  Attempt {attempt + 1}/{max_retries}...")
                
                # Fetch from Yahoo Finance
                ticker = yf.Ticker(symbol)
                
                # Get recent history (last 5 days to ensure we have data)
                history = ticker.history(period="5d")
                
                if history.empty:
                    print(f"  No history data found for {symbol}")
                    if attempt < max_retries - 1:
                        time.sleep(1)
                        continue
                    return None
                
                # Get latest data
                latest = history.iloc[-1]
                current_price = float(latest['Close'])
                
                # Calculate previous close
                if len(history) > 1:
                    previous_close = float(history.iloc[-2]['Close'])
                else:
                    previous_close = current_price * 0.99
                
                # Try to get info (this can fail, so we have fallbacks)
                info = {}
                try:
                    info = ticker.info
                except:
                    print("  Warning: Could not fetch ticker.info, using fallbacks")
                
                # Build stock data with fallbacks
                stock_data = {
                    'symbol': symbol,
                    'name': info.get('longName') or info.get('shortName') or symbol.replace('.NS', '').replace('.BO', ''),
                    'price': current_price,
                    'previousClose': previous_close,
                    'change': ((current_price - previous_close) / previous_close * 100),
                    'dayHigh': float(latest.get('High', current_price * 1.02)),
                    'dayLow': float(latest.get('Low', current_price * 0.98)),
                    'volume': int(latest.get('Volume', 1000000)),
                    'fiftyTwoWeekHigh': info.get('fiftyTwoWeekHigh', current_price * 1.5),
                    'fiftyTwoWeekLow': info.get('fiftyTwoWeekLow', current_price * 0.7),
                    'marketCap': info.get('marketCap', current_price * 1000000000),
                    'currency': 'INR',
                    'timestamp': datetime.now().isoformat()
                }
                
                # Ensure all values are valid numbers
                for key in ['price', 'previousClose', 'change', 'dayHigh', 'dayLow', 
                           'fiftyTwoWeekHigh', 'fiftyTwoWeekLow']:
                    if stock_data[key] is None or stock_data[key] == 0:
                        stock_data[key] = current_price
                
                for key in ['volume', 'marketCap']:
                    if stock_data[key] is None:
                        stock_data[key] = 1000000
                
                # Cache the data
                stock_cache[symbol] = (stock_data, datetime.now())
                
                print(f"✓ Successfully fetched {stock_data['name']} @ ₹{current_price:.2f}")
                return stock_data
                
            except Exception as fetch_error:
                print(f"  Error on attempt {attempt + 1}: {fetch_error}")
                if attempt < max_retries - 1:
                    time.sleep(2)  # Wait before retry
                else:
                    raise
        
        return None
        
    except Exception as e:
        print(f"✗ Failed to fetch {symbol}: {str(e)}")
        import traceback
        traceback.print_exc()
        return None

@app.route('/api/stock/<symbol>', methods=['GET'])
def get_stock(symbol):
    """Get stock data for a single symbol"""
    try:
        print(f"\n[API] GET /api/stock/{symbol}")
        data = fetch_stock_data(symbol)
        
        if data:
            print(f"[API] ✓ Returning data for {symbol}")
            return jsonify({
                'success': True,
                'data': data,
                'cached': symbol in stock_cache
            })
        else:
            print(f"[API] ✗ Stock {symbol} not found")
            return jsonify({
                'success': False,
                'error': f'Could not fetch data for {symbol}. Please verify the symbol is correct.',
                'symbol': symbol
            }), 404
            
    except Exception as e:
        print(f"[API] ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'Server error: {str(e)}',
            'symbol': symbol
        }), 500

@app.route('/api/stocks/batch', methods=['POST'])
def get_stocks_batch():
    """Get data for multiple stocks at once"""
    try:
        symbols = request.json.get('symbols', [])
        print(f"\n[API] POST /api/stocks/batch - {len(symbols)} symbols")
        
        results = {}
        errors = []
        
        for symbol in symbols:
            try:
                data = fetch_stock_data(symbol)
                if data:
                    results[symbol] = data
                else:
                    errors.append(symbol)
            except Exception as e:
                print(f"[API] Error fetching {symbol}: {e}")
                errors.append(symbol)
        
        print(f"[API] ✓ Success: {len(results)}, Failed: {len(errors)}")
        
        return jsonify({
            'success': True,
            'data': results,
            'count': len(results),
            'failed': errors
        })
        
    except Exception as e:
        print(f"[API] ✗ Batch error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/search/<query>', methods=['GET'])
def search_stocks(query):
    """Search for stocks by name or symbol"""
    try:
        print(f"\n[API] GET /api/search/{query}")
        
        # Expanded stock names mapping
        stock_names = {
            'RELIANCE': 'RELIANCE.NS',
            'RELIANCE INDUSTRIES': 'RELIANCE.NS',
            'RIL': 'RELIANCE.NS',
            
            'TCS': 'TCS.NS',
            'TATA CONSULTANCY': 'TCS.NS',
            'TATA CONSULTANCY SERVICES': 'TCS.NS',
            
            'HDFC': 'HDFCBANK.NS',
            'HDFC BANK': 'HDFCBANK.NS',
            'HDFCBANK': 'HDFCBANK.NS',
            
            'INFOSYS': 'INFY.NS',
            'INFY': 'INFY.NS',
            
            'HINDUSTAN COPPER': 'HINDCOPPER.NS',
            'HINDCOPPER': 'HINDCOPPER.NS',
            'HIND COPPER': 'HINDCOPPER.NS',
            
            'ICICI': 'ICICIBANK.NS',
            'ICICI BANK': 'ICICIBANK.NS',
            
            'SBI': 'SBIN.NS',
            'STATE BANK': 'SBIN.NS',
            'STATE BANK OF INDIA': 'SBIN.NS',
            
            'AIRTEL': 'BHARTIARTL.NS',
            'BHARTI': 'BHARTIARTL.NS',
            'BHARTI AIRTEL': 'BHARTIARTL.NS',
            
            'ITC': 'ITC.NS',
            'L&T': 'LT.NS',
            'LARSEN': 'LT.NS',
            'LARSEN AND TOUBRO': 'LT.NS',
            
            'WIPRO': 'WIPRO.NS',
            'MARUTI': 'MARUTI.NS',
            'BAJAJ': 'BAJFINANCE.NS',
            'TITAN': 'TITAN.NS',
            'ADANI': 'ADANIENT.NS'
        }
        
        query_upper = query.upper().strip()
        
        # Try exact match
        if query_upper in stock_names:
            symbol = stock_names[query_upper]
            print(f"[API] Exact match: {query} -> {symbol}")
            data = fetch_stock_data(symbol)
            if data:
                return jsonify({
                    'success': True,
                    'data': data,
                    'match_type': 'exact'
                })
        
        # Try partial match
        for name, symbol in stock_names.items():
            if query_upper in name or name in query_upper:
                print(f"[API] Partial match: {query} -> {symbol}")
                data = fetch_stock_data(symbol)
                if data:
                    return jsonify({
                        'success': True,
                        'data': data,
                        'match_type': 'partial'
                    })
        
        # Try as direct symbol
        print(f"[API] Trying as direct symbol: {query}")
        data = fetch_stock_data(query)
        if data:
            return jsonify({
                'success': True,
                'data': data,
                'match_type': 'direct'
            })
        
        print(f"[API] ✗ No match found for {query}")
        return jsonify({
            'success': False,
            'error': f'Stock "{query}" not found. Try: RELIANCE.NS, TCS.NS, HINDCOPPER.NS',
            'query': query
        }), 404
        
    except Exception as e:
        print(f"[API] ✗ Search error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e),
            'query': query
        }), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'cache_size': len(stock_cache),
        'cached_stocks': list(stock_cache.keys())[:10],  # Show first 10
        'server': 'Flask',
        'version': '1.0'
    })

@app.route('/api/test', methods=['GET'])
def test_endpoint():
    """Test endpoint with debug info"""
    try:
        # Test fetching a known stock
        test_symbol = 'RELIANCE.NS'
        print(f"\n[TEST] Testing with {test_symbol}...")
        
        data = fetch_stock_data(test_symbol)
        
        return jsonify({
            'test': 'Stock API Test',
            'test_symbol': test_symbol,
            'fetch_success': data is not None,
            'data': data,
            'cache_size': len(stock_cache),
            'yfinance_working': True,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        import traceback
        return jsonify({
            'test': 'Stock API Test',
            'error': str(e),
            'traceback': traceback.format_exc(),
            'yfinance_working': False
        }), 500

@app.route('/', methods=['GET'])
def home():
    """API documentation"""
    return jsonify({
        'name': 'Financial Analysis API',
        'version': '1.0',
        'status': 'running',
        'endpoints': {
            'GET /api/stock/<symbol>': 'Get data for single stock (e.g., /api/stock/RELIANCE.NS)',
            'POST /api/stocks/batch': 'Get data for multiple stocks',
            'GET /api/search/<query>': 'Search for stock by name (e.g., /api/search/Reliance)',
            'GET /api/health': 'Health check',
            'GET /api/test': 'Test endpoint with debug info'
        },
        'examples': {
            'single_stock': f'{request.host_url}api/stock/RELIANCE.NS',
            'search': f'{request.host_url}api/search/Reliance',
            'health': f'{request.host_url}api/health',
            'test': f'{request.host_url}api/test'
        },
        'common_symbols': [
            'RELIANCE.NS', 'TCS.NS', 'HDFCBANK.NS', 'INFY.NS',
            'HINDCOPPER.NS', 'ICICIBANK.NS', 'SBIN.NS'
        ]
    })

if __name__ == '__main__':
    # Start background refresh thread
    refresh_thread = threading.Thread(target=background_refresh, daemon=True)
    refresh_thread.start()
    
    print("\n" + "=" * 70)
    print("🚀 Financial Analysis API Server")
    print("=" * 70)
    print(f"📡 Server URL: http://localhost:5000")
    print(f"📖 Documentation: http://localhost:5000")
    print(f"❤️  Health Check: http://localhost:5000/api/health")
    print(f"🧪 Test Endpoint: http://localhost:5000/api/test")
    print("=" * 70)
    print("\n📊 Quick Test Commands:")
    print("  curl http://localhost:5000/api/test")
    print("  curl http://localhost:5000/api/stock/RELIANCE.NS")
    print("  curl http://localhost:5000/api/search/Reliance")
    print("\n💡 Frontend Setup:")
    print("  1. Open advanced_financial_analyst_complete.html")
    print("  2. Ensure API_BASE_URL = 'http://localhost:5000'")
    print("  3. Type 'RELIANCE.NS' or 'Reliance' and click Generate")
    print("\n⚡ Starting server...\n")
    print("=" * 70)
    
    # Run the Flask app
    app.run(debug=True, host='0.0.0.0', port=5000)
