"""Static watchlists used for the "auto scan" universe.

Free data sources don't offer a full-market screener API, so instead of
scanning literally every stock/coin we scan a curated list matching what's
actually tradable on the platforms this project targets:

  - Crypto: coins listed on Bitkub (Thai exchange) that also have a liquid
    USDT pair on Binance, since Binance is used for OHLCV/technical data
    (verified by cross-referencing api.bitkub.com/api/market/symbols against
    Binance's exchangeInfo — see below). Prices on Binance and Bitkub track
    the same underlying asset closely, so Binance klines are a solid proxy
    for technical analysis even though the actual trade happens on Bitkub.
  - Stocks: liquid US large-caps + liquid Thai SET stocks, both tradable
    through Dime (which offers Thai and fractional US stock trading).

Edit these lists directly if your personal watchlist differs.
"""

# --- Crypto (Bitkub-listed, Binance USDT pair available) -------------------
# Ticker -> display name.
CRYPTO_NAMES = {
    "BTC": "Bitcoin", "ETH": "Ethereum", "BNB": "BNB", "SOL": "Solana",
    "XRP": "XRP", "ADA": "Cardano", "DOGE": "Dogecoin", "AVAX": "Avalanche",
    "LINK": "Chainlink", "DOT": "Polkadot", "TRX": "TRON", "POL": "Polygon",
    "SHIB": "Shiba Inu", "NEAR": "NEAR Protocol", "UNI": "Uniswap",
    "XLM": "Stellar", "ICP": "Internet Computer", "APT": "Aptos",
    "ATOM": "Cosmos", "FIL": "Filecoin", "HBAR": "Hedera", "ALGO": "Algorand",
    "SAND": "The Sandbox", "MANA": "Decentraland", "AXS": "Axie Infinity",
    "GALA": "Gala", "CHZ": "Chiliz", "ENJ": "Enjin Coin", "KSM": "Kusama",
    "COMP": "Compound", "AAVE": "Aave", "SNX": "Synthetix", "CRV": "Curve DAO",
    "SUSHI": "SushiSwap", "GRT": "The Graph", "1INCH": "1inch", "QNT": "Quant",
    "ARB": "Arbitrum", "OP": "Optimism", "INJ": "Injective", "TIA": "Celestia",
    "SEI": "Sei", "SUI": "Sui", "STRK": "Starknet", "JUP": "Jupiter",
    "PEPE": "Pepe", "WIF": "dogwifhat", "BONK": "Bonk", "FLOKI": "Floki",
    "TRUMP": "Official Trump", "LDO": "Lido DAO", "RSR": "Reserve Rights",
    "IOTX": "IoTeX", "ANKR": "Ankr", "CELO": "Celo", "FLOW": "Flow",
    "GMT": "STEPN", "CAKE": "PancakeSwap", "MASK": "Mask Network",
    "JASMY": "JasmyCoin", "WOO": "WOO Network", "DYDX": "dYdX",
    "ENS": "Ethereum Name Service", "BLUR": "Blur", "PYTH": "Pyth Network",
    "FET": "Fetch.ai", "RAY": "Raydium", "ORCA": "Orca", "PENDLE": "Pendle",
    "VIRTUAL": "Virtuals Protocol",
}

CRYPTO_UNIVERSE = list(CRYPTO_NAMES.keys())

# Binance quotes everything against USDT; verified these all trade there.
CRYPTO_BINANCE_SYMBOL = {ticker: f"{ticker}USDT" for ticker in CRYPTO_UNIVERSE}


# --- Stocks ------------------------------------------------------------------
# US large-caps (Yahoo Finance ticker -> display name).
US_STOCK_NAMES = {
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

# Liquid Thai SET stocks tradable via Dime (Yahoo Finance uses the .BK suffix).
TH_STOCK_NAMES = {
    "PTT.BK": "PTT", "AOT.BK": "Airports of Thailand", "CPALL.BK": "CP All",
    "ADVANC.BK": "Advanced Info Service (AIS)", "KBANK.BK": "Kasikornbank",
    "SCB.BK": "SCB X", "BBL.BK": "Bangkok Bank", "SCC.BK": "Siam Cement",
    "DELTA.BK": "Delta Electronics", "GULF.BK": "Gulf Energy Development",
    "PTTEP.BK": "PTT Exploration & Production", "CPF.BK": "Charoen Pokphand Foods",
    "TRUE.BK": "True Corporation", "BDMS.BK": "Bangkok Dusit Medical Services",
    "CRC.BK": "Central Retail", "OSP.BK": "Osotspa", "TOP.BK": "Thai Oil",
    "IVL.BK": "Indorama Ventures", "HMPRO.BK": "Home Product Center",
    "MINT.BK": "Minor International", "BH.BK": "Bumrungrad Hospital",
    "EGCO.BK": "Electricity Generating", "KTB.BK": "Krung Thai Bank",
    "TIDLOR.BK": "Ngern Tid Lor", "WHA.BK": "WHA Corporation",
    "BJC.BK": "Berli Jucker", "CBG.BK": "Carabao Group",
    "SAWAD.BK": "Srisawad Corporation", "TU.BK": "Thai Union Group",
    "AWC.BK": "Asset World Corp",
}

STOCK_NAMES = {**US_STOCK_NAMES, **TH_STOCK_NAMES}
STOCK_UNIVERSE = list(STOCK_NAMES.keys())
