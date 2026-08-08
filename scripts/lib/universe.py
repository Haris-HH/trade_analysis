"""Static watchlists used for the "auto scan" universe.

Free data sources (CoinGecko / Yahoo Finance) don't offer a free full-market
screener API, so instead of scanning literally every stock/coin we scan a
curated list of the most liquid, most-followed names. This keeps API usage
inside free-tier rate limits while still covering the names most retail
traders care about.
"""

# Top large-cap / high-liquidity US stocks (proxy for "most popular").
STOCK_UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK-B", "AVGO",
    "JPM", "LLY", "V", "UNH", "XOM", "MA", "COST", "HD", "PG", "NFLX", "JNJ",
    "BAC", "CRM", "AMD", "ORCL", "KO", "PEP", "ADBE", "WMT", "MCD", "DIS",
    "ABNB", "INTC", "QCOM", "TXN", "PLTR", "UBER", "SHOP", "COIN", "SOFI",
    "SMCI",
]

# Company names used to build better news search queries than raw tickers.
STOCK_NAMES = {
    "AAPL": "Apple", "MSFT": "Microsoft", "GOOGL": "Google", "AMZN": "Amazon",
    "NVDA": "Nvidia", "META": "Meta Platforms", "TSLA": "Tesla",
    "BRK-B": "Berkshire Hathaway", "AVGO": "Broadcom", "JPM": "JPMorgan Chase",
    "LLY": "Eli Lilly", "V": "Visa", "UNH": "UnitedHealth", "XOM": "Exxon Mobil",
    "MA": "Mastercard", "COST": "Costco", "HD": "Home Depot", "PG": "Procter & Gamble",
    "NFLX": "Netflix", "JNJ": "Johnson & Johnson", "BAC": "Bank of America",
    "CRM": "Salesforce", "AMD": "AMD", "ORCL": "Oracle", "KO": "Coca-Cola",
    "PEP": "PepsiCo", "ADBE": "Adobe", "WMT": "Walmart", "MCD": "McDonald's",
    "DIS": "Disney", "ABNB": "Airbnb", "INTC": "Intel", "QCOM": "Qualcomm",
    "TXN": "Texas Instruments", "PLTR": "Palantir", "UBER": "Uber",
    "SHOP": "Shopify", "COIN": "Coinbase", "SOFI": "SoFi", "SMCI": "Super Micro Computer",
}

# CoinGecko IDs for the top crypto assets we track (used for market data + names).
CRYPTO_UNIVERSE = [
    "bitcoin", "ethereum", "binancecoin", "solana", "ripple", "cardano",
    "dogecoin", "avalanche-2", "chainlink", "polkadot", "tron", "toncoin",
    "matic-network", "litecoin", "shiba-inu", "near", "uniswap", "stellar",
    "internet-computer", "aptos",
]

CRYPTO_NAMES = {
    "bitcoin": "Bitcoin", "ethereum": "Ethereum", "binancecoin": "BNB",
    "solana": "Solana", "ripple": "XRP", "cardano": "Cardano",
    "dogecoin": "Dogecoin", "avalanche-2": "Avalanche", "chainlink": "Chainlink",
    "polkadot": "Polkadot", "tron": "TRON", "toncoin": "Toncoin",
    "matic-network": "Polygon", "litecoin": "Litecoin", "shiba-inu": "Shiba Inu",
    "near": "NEAR Protocol", "uniswap": "Uniswap", "stellar": "Stellar",
    "internet-computer": "Internet Computer", "aptos": "Aptos",
}

# CoinGecko id -> Binance symbol (for OHLCV klines) and display info.
CRYPTO_BINANCE_SYMBOL = {
    "bitcoin": "BTCUSDT", "ethereum": "ETHUSDT", "binancecoin": "BNBUSDT",
    "solana": "SOLUSDT", "ripple": "XRPUSDT", "cardano": "ADAUSDT",
    "dogecoin": "DOGEUSDT", "avalanche-2": "AVAXUSDT", "chainlink": "LINKUSDT",
    "polkadot": "DOTUSDT", "tron": "TRXUSDT", "toncoin": "TONUSDT",
    "matic-network": "MATICUSDT", "litecoin": "LTCUSDT", "shiba-inu": "SHIBUSDT",
    "near": "NEARUSDT", "uniswap": "UNIUSDT", "stellar": "XLMUSDT",
    "internet-computer": "ICPUSDT", "aptos": "APTUSDT",
}
