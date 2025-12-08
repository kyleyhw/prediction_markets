# Polymarket API Metadata & Tags

This document outlines the metadata structure returned by the Polymarket Gamma API and lists currently active tags/categories.

## Event Object Structure
The top-level object returned by `/events` contains high-level metadata about a group of markets (e.g. "Will Trump do X?").

| Key | Type | Description |
| :--- | :--- | :--- |
| `id` | string | Unique event ID |
| `title` | string | Display title of the event |
| `slug` | string | URL slug for the event page |
| `description` | string | Detailed resolution criteria and description |
| `startDate` | string (ISO) | Event creation/start date |
| `endDate` | string (ISO) | Expected resolution date |
| `creationDate` | string (ISO) | Date the event was created in the system |
| `image` | string (URL) | URL to event image/thumbnail |
| `volume` | string (float) | Total volume across all markets in this event |
| `volume24hr` | float | Volume in the last 24 hours |
| `liquidity` | string (float) | Total liquidity |
| `tags` | list[dict] | List of category tags (see below) |
| `markets` | list[dict] | List of individual markets within this event |

## Market Object Structure
The `markets` list contained within an event object.

| Key | Type | Description |
| :--- | :--- | :--- |
| `id` | string | Unique market ID |
| `question` | string | Specific question (often same as event title for single-market events) |
| `slug` | string | URL slug for this specific market |
| `outcomes` | list[string] | Resolution outcomes (e.g. `["Yes", "No"]`) |
| `outcomePrices` | list[string] | Current price of each outcome (str representation of float) |
| `clobTokenIds` | list[string] | Token IDs for the Orderbook (CLOB) |
| `active` | boolean | Whether the market is currently active |
| `closed` | boolean | Whether the market has ended/settled |
| `volume` | string | Total volume for this specific market |
| `volume24hr` | float | 24h volume for this market |
| `liquidity` | string | Liquidity metric for this market |
| `acceptingOrders` | boolean | If the market handles new orders |
| `ready` | boolean | If the market is fully deployed and ready |

## Active Tags (Categories)
*Last Updated: 2025-12-08 03:26 UTC*

Below is a non-exhaustive list of tags discovered from active markets. These can be used with the `find_interesting_markets.py` script.

Total Unique Tags Found: 739

### All Discovered Tags (A-Z)
$LIBRA, $wif, $YZY, 15M, 1H, 2025 Predictions, 2026 FIFA World Cup, 4H, AAPL, abortion, Abraham Accords, ACC, Acquisitions, ADA, AFC, Afghanistan, AHL, AI, ai technology, Airdrops, aliens, All, All-In, Almanak, Altman, amazon, America Party, AMZN, andrew tate, Ansem , anthropic, antitrust, Apple, Approval, Arc, argentina, Argentina Election, ARS, artificail intelligence, artificial intelligence, Asia, Assad, Aster, astroid, ATH, Atlanta, atmoic, atomic, Awards, Axiom, Aztec, Backpack, Bahrain, balance, Barstool, baseball, Based, Basketball, bat, Battle of the Sexes, BCRA, bernie sanders, Best of 2025, Biden, Big 10, Big 12, Big Beautiful Bill, Big East, Big Tech, Bill Belichick, Bird Flu, bitboy, Bitcoin, BLACKPINK, BNB, BOE, Boeing, Bolton, bomb, box office, Boxing, Brazil, Brazil Serie A, break up, Breaking News, brics, btc, Bucharest Mayor, budget, Buenos Aires, bundesliga, Bundesliga 2, bus, Business, Business News, buy, Bybit Hack, Cabinet, California, California Governor, Call of Duty, Canada, Canadian Election, Carabao Cup, Cardano, cars, CBB, cdc, CEHL, Celebrities, CFB, CFB Playoffs, CFTC, Chainlink, Champions League, Charlie Kirk, chatgpt, Chelsea Clinton, Chess, Chile Election, China, ChinaTalk, chris christie, christmas, CIA, Citygroup, climate, climate & weather, Climate Change, clinton, coachella, cobie, coinbase, Collectibles, college football, Colombia, Comey, Commodities, Congress, Consensys, counter strike 2, Coupe de France, Court, court cases, Courts, covid, Cowboys vs Eagles, cpi, Cracker Barrel, Creators, Cricket, Cricket New Zealand, Cricket Test, Cricket UAE, crime, crimea, Crypto, Crypto Policy, Crypto Prices, Crypto Summit, CryptoPunks, cs2, cuba, Culture, currency, Curry, CWBB, cz, Czech Election, Daily, dallas, Darts, Databricks, david friedberg, DAX, DC, Declassification, DeepSeek, defense, Defi App, deficit, DEHL, democrat, democratic presidential nomination, Denmark, Denmark Superliga, depeg, Derivatives, Diddy, discord, disease, Divorce, DJI, DOGE, Dogecoin, dollar, donestk, donetsk, Dota 2, Drake, drugs, druze, dutch, Dutch Election, Earn 4%, Earnings, Earnings Calls, earthquake, Economic Policy, economics, Economy, EdgeX, EFL Championship, EFL Cup, egypt, Elections, Elon, Elon Musk, England, EPL, Epstein, Equities, Eredivisie, Eric Adams, Esports, ETF, ethena, Ethereum, eu, Euroleague Basketball, Europa Conference League, Europe, Eurovision, exchange, Exchange Rate, Extended, f1, FA Cup, facebook, Fannie Mae, Fantasy Football, fbi, fdv, Featured, Fed, Fed Rates, Fees, Felix, FIFA World Cup, Finance, fire, flee, Florida, Fogo, food, football, foreign affairs, Foreign Policy, forex, Formula 1, France, Freddie Mac, ftc, FTSE, Games, GameStop, Ganja, Garden Cup, gas, gavin newsom, Gaza, Gaza Floatilla, gemini, Gemini 3, Geopolitics, Germany, Ghislaine Maxwell, Giannis, giza, Global, Global Elections, Global Temp, global warming, GME, GMGN, Gold, Golden Globes, Golf, GOOGL, google, Gov Shutdown, Governance, government, gpt, GPT-5, GRAMMY, Grammys, Greenland, Greta Thunberg, grizzlies, Grok, Grokipedia, Grooming Gangs, gta 6, GTA VI, guyana, H-1B, H1b, H5N1, hack, hamas, handball, Hannah Dugan, Harmonix, health, Heisman, Hezbollah, HHS, Hide From New, Hit First, Hit Price, HKU5-CoV-2, Hochul, Hockey, hollywood, Honduras Election, Hong Kong, house, houthis, HSI, Humidify, Hungary, hurricane, Hurricanes, hyperliquid, Iceman, Immigration, Immigration/Border, India, India-Pakistan, Indicies, indonesia, Industry, Infinex, Inflation, Infrared, International T20, internet, IPO, IPOs, Iran, iraq, Israel, italy, Ja Morant, Jake Paul, jan 6, january 6, Japan, Jason Calacanis, javier milei, Jayson Tatum, Jerome, Jerome Powell, Jews, Jobs Report, Julani, K-pop, Kaito, kalshi, Kanye, Kash Patel, kashmir, keir, Kennedy, khafare, Khamenei, KHL, Kim Jong Un, knicks, Kpop, kraken, KSA, Kup'yans'k-Vuzlovyi, Kupyansk, Kuwait, LA, La Liga, La Liga 2, LA Protests, Lanka Premier League, Larry Ellison, Las Vegas, league of legends, Lebanon, legal, Libra, Liga MX, Lighter, Ligue 1, Ligue 2, Lionel Messi, Lisa Cook, list, Llama 5, llm, lol, London, Los Angeles, Louvre, Louvre heist, LV, Macro Election 1, Macro Election 2, Macro Geopolitics, Macro Graph, Macro Indicators, Macro Single, Macron, maduro, MAGA, magazine, Mamdani, Marijuana, Mark Carney, Maxwell, mayor, Mayoral Elections, MBC, media, MegaETH, Mentions, Meta, Meta vs FTC, metals, Metamask, mexico, MH370, Michael Saylor, MicroStrategy, Middle East, Midterms, milei, military, Military Actions, Mindshare, minnesota, MLB, Monthly, Monthly Hit, mov, Movies, MrBeast, MSFT, MSTR, Multi Strikes, Music, mvp, nasa, National Championship, nato, Natural Disaster, natural disasters, NBA, NBA Champion, NBA Finals, NCAA, NCAA Basketball, NCAA Football, ncaab, NDX, Neg Risk, netanyahu, netflix, Netherlands, New Pope, New York, New York City, NFL, NFL Draft, NFLX, nft, NHL, Nigeria, NIK, north korea, Nov 4 Elections, nuclear, Nuclear Non-Proliferation Treaty, NVDA, NYA, nyc, NYC Mayor, NYPD, NYSE, O'Donnell, obama, official rate, oil, Olympics, Oman, OPEN, Open AI, OpenAI, opensea, Optimus, Oracle, Orderly, Oscars, Ostium, Other, Pacifica, pakistan, palestine, palisades, Pandemics, Paradex, pardon, parlay, Parlays, peace, Peak, pedophile, Pengu, pepe, Perplexity, PGA TOUR, phantom, Philippines, Pierre, Plasma, playoffs, PLTR, Pokemon, Poker game, Poland, Politics, Polymarket, Pope Leo XIV, Pot, poty, powell, Pre-Market, Prediction Markets, Premier League, President, Primaries, Primeira Liga, prop, prop 50, Proposition 50, Pudgy, Pump.Fun, PUP, putin, qatar, quantum, Rainbow Six Siege, Ranger, Reality TV, Recurring, redistricting, redskins, Reefer, referendum, resign, Reya, RFK, RFK Jr, rich, Ripple, robert f. kennedy jr., Robert Kennedy Jr., Robot, Romania, Roy lee, russia, Russia Capture, RUT, RWA, S&P 500, Sam, sam altman, Sam Bankman-Fried, sama, saudi arabia, Saudi Professional League, SBF, sceince, Science, Scottish Premiership, SCOTUS, sea, Seattle, sec, Security Guarantee, self driving, Senate, sentate, Sentient, Seoul, Serie A, Serie B, SHL, SNHL, Soccer, social media, sol, Solana, Solstice, South Korea, space, SpaceX, spain, Sports, spotify, SPX, Stablecoins, StandX, Stanley Cup, Starmer, startup, Steam, Stock Prices, Stocks, Stripe, Sudan, Super Bowl, Super Bowl LX, sweden, sydney sweeney, Syria, Süper Lig, taiwan, Tariffs, tax cut, Taxes, Taylor Swift, TBPN, Tech, tech industry, tech news, technology, ted cruz, Tempo, Tennis, Tesla, Thailand-Cambodia, thc, The Masters, Theo, third, TikTok, Time, Tito, Today 🚀, Token Sales, Tomahawk, Tonga, top model, Toronto, trade deal, Trade War, travis kelce, travle, Treasuries, Trump, Trump Presidency, Trump vs Elon, Trump x al-Sharaa, Trump x Mamdani, Trump x Saudi, Trump-Putin, Trump-Xi, Trump-Zelensky, Trump-Zelenskyy, TSLA, tucker carlson, Turkey, Tweet Markets, Twitter, Türkiye, U.S. Politics, UAE, UCL, UEFA Europa League, UEL, UFC, uk, Ukraine, Ukraine Map, uniswap, United Arab Emirates, united kingdom, Up or Down, us, US Election, us government, us law, US Politics, US-Iran, USD.AI, usdt, vaccine, Valorant, Variational, Venezuela, Ventuals, video games, VOOI, WashPO, Weather, Weekly, West Bank, wif, Windows, World, world affairs, world cup, world election, World Elections, Worldcoin, Wuhan, X, xAI, xi jinping, XRP, xtrd-1, Yearly, Yearly Hit, Yemen, YouTube, YZY, Zama, Zcash, zelensky, zelenskyy, Zohran Mamdani, Zuckerberg
