# Polymarket API Metadata & Structures

This document outlines the **metadata structure** returned by the Polymarket Gamma API. It provides detailed origins, interpretations, and calculations for the core fields found in `Event` and `Market` objects.

## 1. Event Object
The top-level object returned by `/events`. Represents a grouping of markets (e.g., a specific game or election).

### Field Definitions
| Key | Type | Interpretation & Origin | Calculation / Source |
| :--- | :--- | :--- | :--- |
| `id` | `string` | Unique identifier for the market/event. | System generated. |
| `slug` | `string` | URL-friendly identifier. | Derived from the question/title. |
| `question` | `string` | The main title/question of the market. | User/System defined. |
| `volume` | `string` (float) | Total lifetime trading volume in USD. | Aggregated trades. |
| `liquidity` | `string` (float) | Current depth of the orderbook in USD. | Sum of resting limit orders within range. |
| `startDate` | `string` (ISO) | When the event started. | System timestamp. |
| `endDate` | `string` (ISO) | When the market closes/expires. | User defined. |
| `tags` | `array` | List of categories/topics. | User defined or auto-tagged. |

## 2. Real-World Example
*Fetched: 2025-12-10*

| Field | Value | Notes |
| :--- | :--- | :--- |
| `question` | **Will Mistral AI have the top AI model on December 31, 2025?** | Detailed event title. |
| `slug` | `will-mistral-ai-have-the-top-ai-model-on-december-31-2025` | Used in URLs. |
| `volume` | `$4,710` | Low volume example. |
| `liquidity` | `$110,659` | High liquidity relative to volume. |
| `endDate` | `2025-12-31` | Long-term prediction market. |
| `tags` | `["DeepSeek", "2025 Predictions"]` | Specific and broad categorization. |

## 3. Full API Response Example
*Fetched: 2025-12-10*

Below is the complete raw JSON response for an active Event and its primary Market.

### Event Object
<details>
<summary>Click to expand full Event JSON</summary>

```json
{
  "id": "100205",
  "ticker": "FED-RATE-HIKE-2025",
  "slug": "fed-rate-hike-in-2025",
  "title": "Fed rate hike in 2025?",
  "description": "This market will resolve to “Yes” if the upper bound of the target federal funds rate is increased at any point between January 1, 2025 and the Fed's December 2025 meeting...",
  "startDate": "2024-12-29T22:50:33.584839Z",
  "endDate": "2025-12-10T12:00:00Z",
  "image": "https://polymarket-upload.s3.us-east-2.amazonaws.com/will-the-fed-raise-interest-rates-in-2025-PQTEYZMvmAGr.jpg",
  "icon": "https://polymarket-upload.s3.us-east-2.amazonaws.com/will-the-fed-raise-interest-rates-in-2025-PQTEYZMvmAGr.jpg",
  "active": true,
  "closed": false,
  "archived": false,
  "new": false,
  "featured": false,
  "restricted": true,
  "liquidity": "51025.13654",
  "volume": "1089143.410872",
  "openInterest": "0",
  "sortBy": "volume",
  "creationDate": "2024-12-29T17:38:00.916304Z",
  "updatedAt": "2025-12-10T09:19:59.824472Z",
  "featuredImg": null,
  "tags": [
    {
      "id": "100196",
      "label": "Fed Rates",
      "slug": "fed-rates"
    },
    {
      "id": "107",
      "label": "Business",
      "slug": "business"
    },
    {
      "id": "101588",
      "label": "2025 Predictions",
      "slug": "2025-predictions"
    }
  ]
}
```
</details>

### Market Object
<details>
<summary>Click to expand full Market JSON</summary>

```json
{
  "id": "516706",
  "question": "Fed rate hike in 2025?",
  "conditionId": "0x4319532e181605cb15b1bd677759a3bc7f7394b2fdf145195b700eeaedfd5221",
  "slug": "fed-rate-hike-in-2025",
  "resolutionSource": "",
  "endDate": "2025-12-10T12:00:00Z",
  "liquidity": "51025.13654",
  "startDate": "2024-12-29T22:50:33.584839Z",
  "image": "https://polymarket-upload.s3.us-east-2.amazonaws.com/...",
  "description": "This market will resolve to “Yes” if...",
  "outcomes": "[\"Yes\", \"No\"]",
  "outcomePrices": "[\"0.0025\", \"0.9975\"]",
  "volume": "1089143.410872",
  "active": true,
  "closed": false,
  "marketMakerAddress": "",
  "createdAt": "2024-12-29T17:38:00.916304Z",
  "updatedAt": "2025-12-10T09:19:59.824472Z",
  "submitted_by": "0x91430CaD2d3975766499717fA0D66A78D814E5c5",
  "archived": false,
  "resolvedBy": "0x6A9D222616C90FcA5754cd1333cFD9b7fb6a4F74",
  "restricted": true,
  "questionID": "0x8428884817cbc26422ec451101fcedfc5995907a8df6e5905bc29cd30d2867e7",
  "enableOrderBook": true,
  "orderPriceMinTickSize": 0.001,
  "orderMinSize": 5,
  "volumeNum": 1089143.410872,
  "liquidityNum": 51025.13654,
  "endDateIso": "2025-12-10",
  "startDateIso": "2024-12-29",
  "hasReviewedDates": true,
  "volume24hr": 82453.682256,
  "clobTokenIds": "[\"60487116984468020978247225474488676749601001829886755968952521846780452448915\", \"81104637750588840860328515305303028259865221573278091453716127842023614249200\"]",
  "umaBond": "500",
  "umaReward": "5",
  "volume24hrClob": 82453.682256,
  "volumeClob": 1089143.410872,
  "liquidityClob": 51025.13654,
  "acceptingOrders": true,
  "negRisk": false,
  "ready": false,
  "funded": false,
  "acceptingOrdersTimestamp": "2024-12-29T22:49:15Z",
  "competitive": 0.8015991903848178,
  "approved": true,
  "rewardsMinSize": 100,
  "rewardsMaxSpread": 3.5,
  "spread": 0.001,
  "oneDayPriceChange": -0.001,
  "lastTradePrice": 0.004,
  "bestBid": 0.002,
  "bestAsk": 0.003
}
```
</details>

## 4. References
- **Official Documentation**: [Polymarket API Docs](https://docs.polymarket.com/)
- **Gamma API**: [Gamma API Reference](https://docs.polymarket.com/#gamma-api)

## 4. Active Tags (Reference)
*Last Updated: 2025-12-08*

Below is the list of tags discovered from active markets. These can be used with `find_liquid_markets.py`.

### All Discovered Tags (A-Z)
$LIBRA, $wif, $YZY, 15M, 1H, 2025 Predictions, 2026 FIFA World Cup, 4H, AAPL, abortion, Abraham Accords, ACC, Acquisitions, ADA, AFC, Afghanistan, AHL, AI, ai technology, Airdrops, aliens, All, All-In, Almanak, Altman, amazon, America Party, AMZN, andrew tate, Ansem , anthropic, antitrust, Apple, Approval, Arc, argentina, Argentina Election, ARS, artificail intelligence, artificial intelligence, Asia, Assad, Aster, astroid, ATH, Atlanta, atmoic, atomic, Awards, Axiom, Aztec, Backpack, Bahrain, balance, Barstool, baseball, Based, Basketball, bat, Battle of the Sexes, BCRA, bernie sanders, Best of 2025, Biden, Big 10, Big 12, Big Beautiful Bill, Big East, Big Tech, Bill Belichick, Bird Flu, bitboy, Bitcoin, BLACKPINK, BNB, BOE, Boeing, Bolton, bomb, box office, Boxing, Brazil, Brazil Serie A, break up, Breaking News, brics, btc, Bucharest Mayor, budget, Buenos Aires, bundesliga, Bundesliga 2, bus, Business, Business News, buy, Bybit Hack, Cabinet, California, California Governor, Call of Duty, Canada, Canadian Election, Carabao Cup, Cardano, cars, CBB, cdc, CEHL, Celebrities, CFB, CFB Playoffs, CFTC, Chainlink, Champions League, Charlie Kirk, chatgpt, Chelsea Clinton, Chess, Chile Election, China, ChinaTalk, chris christie, christmas, CIA, Citygroup, climate, climate & weather, Climate Change, clinton, coachella, cobie, coinbase, Collectibles, college football, Colombia, Comey, Commodities, Congress, Consensys, counter strike 2, Coupe de France, Court, court cases, Courts, covid, Cowboys vs Eagles, cpi, Cracker Barrel, Creators, Cricket, Cricket New Zealand, Cricket Test, Cricket UAE, crime, crimea, Crypto, Crypto Policy, Crypto Prices, Crypto Summit, CryptoPunks, cs2, cuba, Culture, currency, Curry, CWBB, cz, Czech Election, Daily, dallas, Darts, Databricks, david friedberg, DAX, DC, Declassification, DeepSeek, defense, Defi App, deficit, DEHL, democrat, democratic presidential nomination, Denmark, Denmark Superliga, depeg, Derivatives, Diddy, discord, disease, Divorce, DJI, DOGE, Dogecoin, dollar, donestk, donetsk, Dota 2, Drake, drugs, druze, dutch, Dutch Election, Earn 4%, Earnings, Earnings Calls, earthquake, Economic Policy, economics, Economy, EdgeX, EFL Championship, EFL Cup, egypt, Elections, Elon, Elon Musk, England, EPL, Epstein, Equities, Eredivisie, Eric Adams, Esports, ETF, ethena, Ethereum, eu, Euroleague Basketball, Europa Conference League, Europe, Eurovision, exchange, Exchange Rate, Extended, f1, FA Cup, facebook, Fannie Mae, Fantasy Football, fbi, fdv, Featured, Fed, Fed Rates, Fees, Felix, FIFA World Cup, Finance, fire, flee, Florida, Fogo, food, football, foreign affairs, Foreign Policy, forex, Formula 1, France, Freddie Mac, ftc, FTSE, Games, GameStop, Ganja, Garden Cup, gas, gavin newsom, Gaza, Gaza Floatilla, gemini, Gemini 3, Geopolitics, Germany, Ghislaine Maxwell, Giannis, giza, Global, Global Elections, Global Temp, global warming, GME, GMGN, Gold, Golden Globes, Golf, GOOGL, google, Gov Shutdown, Governance, government, gpt, GPT-5, GRAMMY, Grammys, Greenland, Greta Thunberg, grizzlies, Grok, Grokipedia, Grooming Gangs, gta 6, GTA VI, guyana, H-1B, H1b, H5N1, hack, hamas, handball, Hannah Dugan, Harmonix, health, Heisman, Hezbollah, HHS, Hide From New, Hit First, Hit Price, HKU5-CoV-2, Hochul, Hockey, hollywood, Honduras Election, Hong Kong, house, houthis, HSI, Humidify, Hungary, hurricane, Hurricanes, hyperliquid, Iceman, Immigration, Immigration/Border, India, India-Pakistan, Indicies, indonesia, Industry, Infinex, Inflation, Infrared, International T20, internet, IPO, IPOs, Iran, iraq, Israel, italy, Ja Morant, Jake Paul, jan 6, january 6, Japan, Jason Calacanis, javier milei, Jayson Tatum, Jerome, Jerome Powell, Jews, Jobs Report, Julani, K-pop, Kaito, kalshi, Kanye, Kash Patel, kashmir, keir, Kennedy, khafare, Khamenei, KHL, Kim Jong Un, knicks, Kpop, kraken, KSA, Kup'yans'k-Vuzlovyi, Kupyansk, Kuwait, LA, La Liga, La Liga 2, LA Protests, Lanka Premier League, Larry Ellison, Las Vegas, league of legends, Lebanon, legal, Libra, Liga MX, Lighter, Ligue 1, Ligue 2, Lionel Messi, Lisa Cook, list, Llama 5, llm, lol, London, Los Angeles, Louvre, Louvre heist, LV, Macro Election 1, Macro Election 2, Macro Geopolitics, Macro Graph, Macro Indicators, Macro Single, Macron, maduro, MAGA, magazine, Mamdani, Marijuana, Mark Carney, Maxwell, mayor, Mayoral Elections, MBC, media, MegaETH, Mentions, Meta, Meta vs FTC, metals, Metamask, mexico, MH370, Michael Saylor, MicroStrategy, Middle East, Midterms, milei, military, Military Actions, Mindshare, minnesota, MLB, Monthly, Monthly Hit, mov, Movies, MrBeast, MSFT, MSTR, Multi Strikes, Music, mvp, nasa, National Championship, nato, Natural Disaster, natural disasters, NBA, NBA Champion, NBA Finals, NCAA, NCAA Basketball, NCAA Football, ncaab, NDX, Neg Risk, netanyahu, netflix, Netherlands, New Pope, New York, New York City, NFL, NFL Draft, NFLX, nft, NHL, Nigeria, NIK, north korea, Nov 4 Elections, nuclear, Nuclear Non-Proliferation Treaty, NVDA, NYA, nyc, NYC Mayor, NYPD, NYSE, O'Donnell, obama, official rate, oil, Olympics, Oman, OPEN, Open AI, OpenAI, opensea, Optimus, Oracle, Orderly, Oscars, Ostium, Other, Pacifica, pakistan, palestine, palisades, Pandemics, Paradex, pardon, parlay, Parlays, peace, Peak, pedophile, Pengu, pepe, Perplexity, PGA TOUR, phantom, Philippines, Pierre, Plasma, playoffs, PLTR, Pokemon, Poker game, Poland, Politics, Polymarket, Pope Leo XIV, Pot, poty, powell, Pre-Market, Prediction Markets, Premier League, President, Primaries, Primeira Liga, prop, prop 50, Proposition 50, Pudgy, Pump.Fun, PUP, putin, qatar, quantum, Rainbow Six Siege, Ranger, Reality TV, Recurring, redistricting, redskins, Reefer, referendum, resign, Reya, RFK, RFK Jr, rich, Ripple, robert f. kennedy jr., Robert Kennedy Jr., Robot, Romania, Roy lee, russia, Russia Capture, RUT, RWA, S&P 500, Sam, sam altman, Sam Bankman-Fried, sama, saudi arabia, Saudi Professional League, SBF, sceince, Science, Scottish Premiership, SCOTUS, sea, Seattle, sec, Security Guarantee, self driving, Senate, sentate, Sentient, Seoul, Serie A, Serie B, SHL, SNHL, Soccer, social media, sol, Solana, Solstice, South Korea, space, SpaceX, spain, Sports, spotify, SPX, Stablecoins, StandX, Stanley Cup, Starmer, startup, Steam, Stock Prices, Stocks, Stripe, Sudan, Super Bowl, Super Bowl LX, sweden, sydney sweeney, Syria, Süper Lig, taiwan, Tariffs, tax cut, Taxes, Taylor Swift, TBPN, Tech, tech industry, tech news, technology, ted cruz, Tempo, Tennis, Tesla, Thailand-Cambodia, thc, The Masters, Theo, third, TikTok, Time, Tito, Today 🚀, Token Sales, Tomahawk, Tonga, top model, Toronto, trade deal, Trade War, travis kelce, travle, Treasuries, Trump, Trump Presidency, Trump vs Elon, Trump x al-Sharaa, Trump x Mamdani, Trump x Saudi, Trump-Putin, Trump-Xi, Trump-Zelensky, Trump-Zelenskyy, TSLA, tucker carlson, Turkey, Tweet Markets, Twitter, Türkiye, U.S. Politics, UAE, UCL, UEFA Europa League, UEL, UFC, uk, Ukraine, Ukraine Map, uniswap, United Arab Emirates, united kingdom, Up or Down, us, US Election, us government, us law, US Politics, US-Iran, USD.AI, usdt, vaccine, Valorant, Variational, Venezuela, Ventuals, video games, VOOI, WashPO, Weather, Weekly, West Bank, wif, Windows, World, world affairs, world cup, world election, World Elections, Worldcoin, Wuhan, X, xAI, xi jinping, XRP, xtrd-1, Yearly, Yearly Hit, Yemen, YouTube, YZY, Zama, Zcash, zelensky, zelenskyy, Zohran Mamdani, Zuckerberg

## 4. Active Tags (Reference)
*Last Updated: 2025-12-08*

Below is the list of tags discovered from active markets. These can be used with `find_interesting_markets.py`.

### All Discovered Tags (A-Z)
$LIBRA, $wif, $YZY, 15M, 1H, 2025 Predictions, 2026 FIFA World Cup, 4H, AAPL, abortion, Abraham Accords, ACC, Acquisitions, ADA, AFC, Afghanistan, AHL, AI, ai technology, Airdrops, aliens, All, All-In, Almanak, Altman, amazon, America Party, AMZN, andrew tate, Ansem , anthropic, antitrust, Apple, Approval, Arc, argentina, Argentina Election, ARS, artificail intelligence, artificial intelligence, Asia, Assad, Aster, astroid, ATH, Atlanta, atmoic, atomic, Awards, Axiom, Aztec, Backpack, Bahrain, balance, Barstool, baseball, Based, Basketball, bat, Battle of the Sexes, BCRA, bernie sanders, Best of 2025, Biden, Big 10, Big 12, Big Beautiful Bill, Big East, Big Tech, Bill Belichick, Bird Flu, bitboy, Bitcoin, BLACKPINK, BNB, BOE, Boeing, Bolton, bomb, box office, Boxing, Brazil, Brazil Serie A, break up, Breaking News, brics, btc, Bucharest Mayor, budget, Buenos Aires, bundesliga, Bundesliga 2, bus, Business, Business News, buy, Bybit Hack, Cabinet, California, California Governor, Call of Duty, Canada, Canadian Election, Carabao Cup, Cardano, cars, CBB, cdc, CEHL, Celebrities, CFB, CFB Playoffs, CFTC, Chainlink, Champions League, Charlie Kirk, chatgpt, Chelsea Clinton, Chess, Chile Election, China, ChinaTalk, chris christie, christmas, CIA, Citygroup, climate, climate & weather, Climate Change, clinton, coachella, cobie, coinbase, Collectibles, college football, Colombia, Comey, Commodities, Congress, Consensys, counter strike 2, Coupe de France, Court, court cases, Courts, covid, Cowboys vs Eagles, cpi, Cracker Barrel, Creators, Cricket, Cricket New Zealand, Cricket Test, Cricket UAE, crime, crimea, Crypto, Crypto Policy, Crypto Prices, Crypto Summit, CryptoPunks, cs2, cuba, Culture, currency, Curry, CWBB, cz, Czech Election, Daily, dallas, Darts, Databricks, david friedberg, DAX, DC, Declassification, DeepSeek, defense, Defi App, deficit, DEHL, democrat, democratic presidential nomination, Denmark, Denmark Superliga, depeg, Derivatives, Diddy, discord, disease, Divorce, DJI, DOGE, Dogecoin, dollar, donestk, donetsk, Dota 2, Drake, drugs, druze, dutch, Dutch Election, Earn 4%, Earnings, Earnings Calls, earthquake, Economic Policy, economics, Economy, EdgeX, EFL Championship, EFL Cup, egypt, Elections, Elon, Elon Musk, England, EPL, Epstein, Equities, Eredivisie, Eric Adams, Esports, ETF, ethena, Ethereum, eu, Euroleague Basketball, Europa Conference League, Europe, Eurovision, exchange, Exchange Rate, Extended, f1, FA Cup, facebook, Fannie Mae, Fantasy Football, fbi, fdv, Featured, Fed, Fed Rates, Fees, Felix, FIFA World Cup, Finance, fire, flee, Florida, Fogo, food, football, foreign affairs, Foreign Policy, forex, Formula 1, France, Freddie Mac, ftc, FTSE, Games, GameStop, Ganja, Garden Cup, gas, gavin newsom, Gaza, Gaza Floatilla, gemini, Gemini 3, Geopolitics, Germany, Ghislaine Maxwell, Giannis, giza, Global, Global Elections, Global Temp, global warming, GME, GMGN, Gold, Golden Globes, Golf, GOOGL, google, Gov Shutdown, Governance, government, gpt, GPT-5, GRAMMY, Grammys, Greenland, Greta Thunberg, grizzlies, Grok, Grokipedia, Grooming Gangs, gta 6, GTA VI, guyana, H-1B, H1b, H5N1, hack, hamas, handball, Hannah Dugan, Harmonix, health, Heisman, Hezbollah, HHS, Hide From New, Hit First, Hit Price, HKU5-CoV-2, Hochul, Hockey, hollywood, Honduras Election, Hong Kong, house, houthis, HSI, Humidify, Hungary, hurricane, Hurricanes, hyperliquid, Iceman, Immigration, Immigration/Border, India, India-Pakistan, Indicies, indonesia, Industry, Infinex, Inflation, Infrared, International T20, internet, IPO, IPOs, Iran, iraq, Israel, italy, Ja Morant, Jake Paul, jan 6, january 6, Japan, Jason Calacanis, javier milei, Jayson Tatum, Jerome, Jerome Powell, Jews, Jobs Report, Julani, K-pop, Kaito, kalshi, Kanye, Kash Patel, kashmir, keir, Kennedy, khafare, Khamenei, KHL, Kim Jong Un, knicks, Kpop, kraken, KSA, Kup'yans'k-Vuzlovyi, Kupyansk, Kuwait, LA, La Liga, La Liga 2, LA Protests, Lanka Premier League, Larry Ellison, Las Vegas, league of legends, Lebanon, legal, Libra, Liga MX, Lighter, Ligue 1, Ligue 2, Lionel Messi, Lisa Cook, list, Llama 5, llm, lol, London, Los Angeles, Louvre, Louvre heist, LV, Macro Election 1, Macro Election 2, Macro Geopolitics, Macro Graph, Macro Indicators, Macro Single, Macron, maduro, MAGA, magazine, Mamdani, Marijuana, Mark Carney, Maxwell, mayor, Mayoral Elections, MBC, media, MegaETH, Mentions, Meta, Meta vs FTC, metals, Metamask, mexico, MH370, Michael Saylor, MicroStrategy, Middle East, Midterms, milei, military, Military Actions, Mindshare, minnesota, MLB, Monthly, Monthly Hit, mov, Movies, MrBeast, MSFT, MSTR, Multi Strikes, Music, mvp, nasa, National Championship, nato, Natural Disaster, natural disasters, NBA, NBA Champion, NBA Finals, NCAA, NCAA Basketball, NCAA Football, ncaab, NDX, Neg Risk, netanyahu, netflix, Netherlands, New Pope, New York, New York City, NFL, NFL Draft, NFLX, nft, NHL, Nigeria, NIK, north korea, Nov 4 Elections, nuclear, Nuclear Non-Proliferation Treaty, NVDA, NYA, nyc, NYC Mayor, NYPD, NYSE, O'Donnell, obama, official rate, oil, Olympics, Oman, OPEN, Open AI, OpenAI, opensea, Optimus, Oracle, Orderly, Oscars, Ostium, Other, Pacifica, pakistan, palestine, palisades, Pandemics, Paradex, pardon, parlay, Parlays, peace, Peak, pedophile, Pengu, pepe, Perplexity, PGA TOUR, phantom, Philippines, Pierre, Plasma, playoffs, PLTR, Pokemon, Poker game, Poland, Politics, Polymarket, Pope Leo XIV, Pot, poty, powell, Pre-Market, Prediction Markets, Premier League, President, Primaries, Primeira Liga, prop, prop 50, Proposition 50, Pudgy, Pump.Fun, PUP, putin, qatar, quantum, Rainbow Six Siege, Ranger, Reality TV, Recurring, redistricting, redskins, Reefer, referendum, resign, Reya, RFK, RFK Jr, rich, Ripple, robert f. kennedy jr., Robert Kennedy Jr., Robot, Romania, Roy lee, russia, Russia Capture, RUT, RWA, S&P 500, Sam, sam altman, Sam Bankman-Fried, sama, saudi arabia, Saudi Professional League, SBF, sceince, Science, Scottish Premiership, SCOTUS, sea, Seattle, sec, Security Guarantee, self driving, Senate, sentate, Sentient, Seoul, Serie A, Serie B, SHL, SNHL, Soccer, social media, sol, Solana, Solstice, South Korea, space, SpaceX, spain, Sports, spotify, SPX, Stablecoins, StandX, Stanley Cup, Starmer, startup, Steam, Stock Prices, Stocks, Stripe, Sudan, Super Bowl, Super Bowl LX, sweden, sydney sweeney, Syria, Süper Lig, taiwan, Tariffs, tax cut, Taxes, Taylor Swift, TBPN, Tech, tech industry, tech news, technology, ted cruz, Tempo, Tennis, Tesla, Thailand-Cambodia, thc, The Masters, Theo, third, TikTok, Time, Tito, Today 🚀, Token Sales, Tomahawk, Tonga, top model, Toronto, trade deal, Trade War, travis kelce, travle, Treasuries, Trump, Trump Presidency, Trump vs Elon, Trump x al-Sharaa, Trump x Mamdani, Trump x Saudi, Trump-Putin, Trump-Xi, Trump-Zelensky, Trump-Zelenskyy, TSLA, tucker carlson, Turkey, Tweet Markets, Twitter, Türkiye, U.S. Politics, UAE, UCL, UEFA Europa League, UEL, UFC, uk, Ukraine, Ukraine Map, uniswap, United Arab Emirates, united kingdom, Up or Down, us, US Election, us government, us law, US Politics, US-Iran, USD.AI, usdt, vaccine, Valorant, Variational, Venezuela, Ventuals, video games, VOOI, WashPO, Weather, Weekly, West Bank, wif, Windows, World, world affairs, world cup, world election, World Elections, Worldcoin, Wuhan, X, xAI, xi jinping, XRP, xtrd-1, Yearly, Yearly Hit, Yemen, YouTube, YZY, Zama, Zcash, zelensky, zelenskyy, Zohran Mamdani, Zuckerberg
