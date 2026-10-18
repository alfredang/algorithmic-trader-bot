"""Course content reused from the IBF course "Machine Learning 101 for Financial Trading"
(Tertiary Infotech Academy Pte Ltd). Generated from the courseware source
(course_data.py, visual_data.py, research_data.py) so the app speaks the course language.
"""
# flake8: noqa

COURSE_TITLE = 'Machine Learning 101 for Financial Trading'
PROVIDER = 'Tertiary Infotech Academy Pte Ltd'
TSC = 'FSE-DAT-3019-1.1 Data Analytics and Computational Modelling'

ALGO_EXPLAIN = {'Algorithm: Moving-Average Crossover (Trend Following)': {'kicker': 'TOPIC 2 · K3',
                                                           'How it works': 'Two moving averages of the close: a fast '
                                                                           'one reacts quickly, a slow one shows the '
                                                                           'trend.',
                                                           'Rule': 'Fast crosses ABOVE slow (golden cross): buy. '
                                                                   'Fast crosses BELOW (death cross): sell or go '
                                                                   'flat.',
                                                           'Works best when': 'Markets trend for months - it rides '
                                                                              'the move and cuts losers when the '
                                                                              'trend turns.',
                                                           'Watch out for': 'Whipsaws in sideways markets; signals '
                                                                            'lag; trade on the next bar, not the '
                                                                            'crossing bar.'},
 'Algorithm: Bollinger Band Mean Reversion': {'kicker': 'TOPIC 2 · K3',
                                              'How it works': 'Bands = 20-day mean +/- 2 standard deviations. A '
                                                              "close outside the band is 'stretched'.",
                                              'Rule': 'Close below the lower band: buy. Exit when the price returns '
                                                      'to the middle band (the mean).',
                                              'Works best when': 'Range-bound markets where over-reactions snap '
                                                                 'back, e.g. a defensive stock such as KO.',
                                              'Watch out for': "Strong trends keep 'stretching' - add a stop-loss or "
                                                               'a trend filter; many small wins, rare big losses.'},
 'Algorithm: RSI and MACD Momentum Oscillators': {'kicker': 'TOPIC 2 · K3',
                                                  'How it works': 'RSI = 100 - 100/(1+RS), RS = average gain / '
                                                                  'average loss over 14 bars. MACD = EMA12 - EMA26.',
                                                  'Rule': 'RSI < 30 oversold / > 70 overbought. MACD crossing above '
                                                          'its 9-EMA signal line = momentum buy.',
                                                  'Works best when': 'As filters or confirmation for a trend or '
                                                                     'mean-reversion rule, not as stand-alone '
                                                                     'predictors.',
                                                  'Watch out for': 'Oscillators can stay overbought in strong '
                                                                   'trends; RSI and MACD are highly correlated with '
                                                                   'price.'},
 'Algorithm: Cross-Sectional Momentum': {'kicker': 'TOPIC 2 · K3',
                                         'How it works': 'Rank a universe by past return (e.g. 12 months, skipping '
                                                         'the last month) each month.',
                                         'Rule': 'Hold the top-ranked assets, avoid or short the bottom-ranked; '
                                                 'rebalance monthly.',
                                         'Works best when': 'Information spreads slowly and winners keep winning for '
                                                            'several months.',
                                         'Watch out for': "Sharp 'momentum crashes' when markets reverse; turnover "
                                                          'costs at every rebalance.'},
 'Algorithm: Donchian Channel Breakout': {'kicker': 'TOPIC 2 · K3',
                                          'How it works': 'Track the highest high and lowest low of the last n bars '
                                                          '(n = 20 here).',
                                          'Rule': 'Close above the 20-day high: buy the breakout. Exit below the '
                                                  '20-day low (or a trailing stop).',
                                          'Works best when': 'New trends start with a break of a range - the rule '
                                                             "used by the 1980s 'Turtle Traders'.",
                                          'Watch out for': 'False breakouts in choppy markets; the channel must use '
                                                           'PREVIOUS bars only (no look-ahead).'},
 'Algorithm: VWAP and TWAP Execution': {'kicker': 'TOPIC 2 · K3',
                                        'How it works': 'Split a large parent order into child orders through the '
                                                        'day to reduce market impact.',
                                        'Rule': 'TWAP: equal slices per time interval. VWAP: slices proportional to '
                                                'the typical volume curve.',
                                        'Works best when': 'Working client or fund orders too large to trade at '
                                                           "once; benchmarked to the day's VWAP.",
                                        'Watch out for': 'VWAP relies on a volume forecast; both are predictable to '
                                                         'other traders - add randomisation.'},
 'Algorithm: Market Making': {'kicker': 'TOPIC 2 · K3',
                              'How it works': 'Quote a bid below and an ask above the mid price at the same time.',
                              'Rule': 'Earn the spread when both sides fill; skew quotes down when long, up when '
                                      'short, to cut inventory.',
                              'Works best when': 'Liquid markets with steady two-way flow - the business of quant '
                                                 'market makers.',
                              'Watch out for': 'Adverse selection by better-informed traders; inventory risk in fast '
                                               'moves; needs low latency.'},
 'Algorithm: Logistic Regression for Direction': {'kicker': 'TOPIC 3 · K4',
                                                  'How it works': 'Fits P(up tomorrow) = 1 / (1 + e^-(b0 + b1 x1 + '
                                                                  '...)) from features known today.',
                                                  'Rule': 'Go long when P(up) exceeds a threshold such as 0.55; '
                                                          'otherwise stay flat.',
                                                  'Works best when': 'A transparent baseline: each coefficient shows '
                                                                     'how a feature moves the probability.',
                                                  'Watch out for': 'Only linear effects unless you engineer '
                                                                   'features; daily direction is close to a coin '
                                                                   'toss.'},
 'Algorithm: Decision Tree and Random Forest': {'kicker': 'TOPIC 3 · K4',
                                                'How it works': 'A tree splits the data on feature thresholds (e.g. '
                                                                'RSI < 30) into leaves with an up/down share.',
                                                'Rule': 'A random forest averages hundreds of trees, each grown on a '
                                                        'random sample of rows and features.',
                                                'Works best when': 'Non-linear, interacting signals - e.g. oversold '
                                                                   'AND low volatility.',
                                                'Watch out for': 'Deep trees memorise noise; limit depth and leaf '
                                                                 'size and validate walk-forward.'},
 'Algorithm: Gradient Boosting (XGBoost)': {'kicker': 'TOPIC 3 · K4',
                                            'How it works': 'Builds trees one after another; each new tree corrects '
                                                            'the errors of the ensemble so far.',
                                            'Rule': 'Prediction = sum of many small trees x learning rate; stop '
                                                    'early when test loss stops falling.',
                                            'Works best when': 'Tabular features such as returns, indicators and '
                                                               'volatility - usually the strongest model.',
                                            'Watch out for': 'Training loss keeps falling while test loss rises: '
                                                             'classic overfitting (see the chart).'},
 'Algorithm: K-Means Clustering for Market Regimes': {'kicker': 'TOPIC 3 · K4',
                                                      'How it works': 'Groups days into k clusters by minimising the '
                                                                      'distance of each day to its cluster centre.',
                                                      'Rule': 'Features: rolling return and volatility '
                                                              '(standardised). Name clusters by their averages.',
                                                      'Works best when': 'Switching or sizing strategies by regime: '
                                                                         'trend in calm markets, cut risk when '
                                                                         'stressed.',
                                                      'Watch out for': 'Fit on past data only; choose k with the '
                                                                       'elbow or silhouette method; regimes shift.'},
 'Algorithm: Principal Component Analysis (PCA)': {'kicker': 'TOPIC 3 · K4',
                                                   'How it works': 'Finds uncorrelated combinations of assets that '
                                                                   'explain the most variance of returns.',
                                                   'Rule': "PC1 of a stock universe is 'the market'; later PCs are "
                                                           'sector or style factors.',
                                                   'Works best when': 'Reducing many correlated features; building '
                                                                      'factor-neutral and pairs portfolios.',
                                                   'Watch out for': 'Standardise first; components change over time; '
                                                                    'PCs are statistical, not economic, factors.'},
 'Method: Walk-Forward Validation': {'kicker': 'TOPIC 3 · K6',
                                     'How it works': 'Train on a past window, test on the next unseen block, then '
                                                     'roll forward and repeat.',
                                     'Rule': 'Never shuffle time series; each test block is genuinely out of sample.',
                                     'Works best when': 'Estimating how a model or parameter set would really have '
                                                        'performed live.',
                                     'Watch out for': 'Overlapping targets leak information - leave a gap between '
                                                      'train and test.'},
 'Method: A/B Testing Two Strategy Variants': {'kicker': 'TOPIC 3 · A5',
                                               'How it works': "Compare variant A and B on the same days: H0 'no "
                                                               "difference' vs H1 'B is better'.",
                                               'Rule': 'Welch / paired t-test on daily returns; bootstrap a 95% CI '
                                                       'of the Sharpe difference.',
                                               'Works best when': 'Deciding which parameter set or filter to promote '
                                                                  'to paper trading.',
                                               'Watch out for': 'If the CI contains 0, do not reject H0; testing 100 '
                                                                'variants gives ~5 false winners.'},
 'Algorithm: Pairs Trading (Hedged Statistical Arbitrage)': {'kicker': 'TOPIC 3 · K6',
                                                             'How it works': 'Long one stock, short a cointegrated '
                                                                             'partner in hedge-ratio proportion: '
                                                                             'market moves cancel.',
                                                             'Rule': 'Spread z > +2: short A / long B. z < -2: long '
                                                                     'A / short B. Exit as z returns to 0.',
                                                             'Works best when': 'Economically linked stocks (KO/PEP) '
                                                                                'whose spread has a stable mean.',
                                                             'Watch out for': 'Cointegration can break; costs on '
                                                                              'both legs; short-borrow; screening '
                                                                              'many pairs.'}}

ALGO_CLASSES = [('Execution algorithms',
  'Work a large order at low cost and market impact',
  'VWAP, TWAP, POV, implementation shortfall, iceberg, smart order routing'),
 ('Market making',
  'Quote bids and offers, earn the spread, manage inventory',
  'Passive market making with resting limit orders'),
 ('Arbitrage',
  'Capture mispricing between related products or markets',
  'ETF versus its basket, index futures versus stocks'),
 ('Directional / alpha',
  'Take a view on the direction of price',
  'Trend following, momentum, breakout, mean reversion, news'),
 ('Statistical arbitrage and pairs',
  'Hedged: long one asset, short a related one; trade the spread',
  'Pairs trading, cointegration, market-neutral baskets'),
 ('Factor and portfolio',
  'Build and rebalance portfolios from return drivers and risk',
  'Value, momentum, size factors; mean-variance optimisation'),
 ('Hedging and risk',
  'Offset unwanted exposure and enforce limits',
  'Delta hedging, beta hedging, pairs hedge, kill switch')]

SEC_HFT = [('Passive market making',
  'Submits non-marketable resting bids and offers that provide liquidity at specified prices'),
 ('Arbitrage', 'Captures pricing inefficiencies between related products or markets, e.g. an ETF and its basket'),
 ('Structural',
  'Exploits structural vulnerabilities in the market or its participants, e.g. stale quotes via faster data'),
 ('Directional', 'Takes a short-term position anticipating an intraday price move in a particular direction')]

ALGO_BY_HORIZON = [('High-frequency', 'Microseconds to seconds', 'Market making, ETF and latency arbitrage'),
 ('Intraday', 'Minutes to hours', 'VWAP / TWAP execution, intraday momentum'),
 ('Swing', 'Days to weeks', 'Mean reversion, pairs trading'),
 ('Position', 'Weeks to months', 'Trend following, factor portfolios')]

ALGO_BY_MODEL = [('Rule-based', 'Fixed if-then rules on indicators, e.g. a moving-average crossover'),
 ('Statistical', 'Econometric tests and models: cointegration, regression, t-tests'),
 ('Machine learning', 'Models learn from labelled data: logistic regression, random forest, XGBoost'),
 ('Reinforcement learning', 'Learns a policy from rewards, e.g. order-execution research'),
 ('LLM and agentic', 'Language models read text and agents plan, code and act under limits')]

PAIRS = [('Why it is a hedge',
  'Long the cheap stock, short the rich one in hedge-ratio proportion: market moves largely cancel'),
 ('Choose the pair', 'Economically linked stocks (e.g. KO and PEP) that are cointegrated, not merely correlated'),
 ('Hedge ratio and spread',
  'Regress log price A on log price B: slope = hedge ratio, residual = the spread (Engle-Granger)'),
 ('Test the spread', 'ADF test on the residual: a stationary spread tends to revert to its mean'),
 ('Trade the z-score', 'Enter when |z| > 2, exit as z returns towards 0; trade both legs on the next bar'),
 ('Risks', 'Cointegration breaks, hedge ratio drifts, double costs, short-borrow, multiple testing')]

PAIRS_EVIDENCE = ('Gatev, Goetzmann and Rouwenhorst (2006): a simple pairs rule on US stocks earned average annualised excess returns '
 'of up to 11% (1962-2002); later studies find smaller and less consistent profits.')

AGENTIC_VS_AGENTS = {'agentic_ai': {'definition': 'The capability of AI to plan and act: it calls tools, uses skills and memory, and '
                              'follows instructions to complete multi-step work when it is asked.',
                'traits': ['Plans multi-step work',
                           'Calls tools and APIs',
                           'Uses skills and memory',
                           'Follows instructions and guardrails',
                           'Runs when invoked; can be one or many agents'],
                'finance_example': "On request, an LLM fetches a stock's bars and news through tools, checks its "
                                   'memory of past trades and proposes an order within its instructions'},
 'ai_agent': {'definition': 'A special class of agentic AI that stands by 24/7 and works all the time: always on, '
                            'woken by schedules, events and messages, with its own long-term memory.',
              'traits': ['Always on: stands by 24/7',
                         'Woken by schedules, events, messages',
                         'Long-term memory across days',
                         'Works without being asked',
                         'Needs hard limits and monitoring'],
              'finance_example': 'A round-the-clock trading agent that watches prices and news overnight and '
                                 'proposes paper trades within risk limits'},
 'comparison': [('Dimension', 'AI Agents', 'Agentic AI'),
                ('What it is',
                 'A special class of agentic AI that is always on',
                 'Capability to plan and act with tools, skills, memory'),
                ('Runtime',
                 'Persistent: stands by 24/7 on a server or PC',
                 'Runs when invoked: a chat, workflow or pipeline'),
                ('Trigger', 'Schedules, events, messages - unprompted', 'A user prompt or a pipeline step'),
                ('Memory',
                 'Long-term memory across days and tasks',
                 'Session or task memory; can use long-term memory'),
                ('Building blocks',
                 'Agentic AI + always-on runtime and scheduler',
                 'LLM + tools + skills + memory + instructions'),
                ('Examples', 'OpenClaw, Hermes Agent, OpenAI Dots', 'Claude Code, ChatGPT with tools, TradingAgents'),
                ('Trading example',
                 '24/7 market and news monitor proposing trades',
                 'On-demand multi-agent analysis before a trade'),
                ('Main risks',
                 'Acting unsupervised overnight; runaway loops',
                 'Hallucination; prompt injection; tool misuse')],
 'spectrum': [('1 · Chatbot', 'Answers one prompt at a time; no tools, no actions'),
              ('2 · Agentic AI', 'Plans and calls tools, skills, memory and instructions when asked'),
              ('3 · Multi-agent agentic system',
               'Specialist agents coordinate: analysts, debate, trader, risk manager'),
              ('4 · AI agent (always on)',
               'Stands by 24/7, wakes on schedules and events, works continuously within limits')]}

ALGO_DEFINITIONS = {'algorithm': 'A finite, step-by-step set of instructions that a computer follows to solve a problem or complete a '
              'task.',
 'algorithmic_trading': 'Using computer programs that follow predefined rules on price, timing, volume or models to '
                        'generate and execute orders automatically, with limited or no human intervention.',
 'benefits': ['Speed: reacts and executes in milliseconds',
              'Discipline: rules remove fear, greed and fatigue',
              'Backtesting: test ideas on historical data first',
              'Lower costs: split large orders to reduce market impact',
              'Scale: monitors many markets and assets around the clock'],
 'risks': ['Technical failure: bugs and outages (Knight Capital, 2012)',
           'Overfitting: great backtests that fail on live data',
           'Black swans and regime change the model has never seen',
           'Feedback loops between algorithms (2010 Flash Crash)',
           'Set-up, data and compliance costs; no guaranteed profit']}

STRATEGY_FAMILIES = [('Trend following',
  'Rides sustained moves in the direction of the trend; cuts losers quickly',
  'Buy when the 50-day moving average crosses above the 200-day'),
 ('Mean reversion',
  'Bets that prices stretched far from their average will snap back',
  'Buy when price closes below the lower Bollinger Band (20-day, 2 std dev)'),
 ('Momentum and breakout',
  'Buys recent winners or prices breaking out of a range, expecting them to keep going',
  'Buy on a close above the 20-day high (Donchian channel breakout)'),
 ('Statistical / pairs arbitrage',
  'Trades the spread between two related assets when it drifts from its normal level',
  'Short the rich leg, buy the cheap leg when the spread z-score exceeds 2'),
 ('Execution algorithms',
  'Split a large order to minimise cost and market impact: VWAP, TWAP, POV, implementation shortfall',
  'POV: trade 10% of market volume until the order is filled'),
 ('Market making',
  'Continuously quotes buy and sell prices, earning the spread while managing inventory',
  'Quote bid and ask around mid-price; skew quotes as inventory builds'),
 ('Index rebalancing / event-driven',
  'Trades predictable flows around index changes, earnings and corporate events',
  'Position ahead of announced index inclusions on the rebalance date'),
 ('Sentiment / NLP',
  'Turns news, filings and social media text into trading signals using NLP or LLMs',
  'Go long when the average FinBERT headline sentiment is strongly positive')]

AGENT_ROLES = [('Orchestrator / Planner', 'Breaks the goal into tasks, routes work to agents and assembles the result'),
 ('Fundamental Analyst', 'Reads filings, earnings and balance sheets to judge intrinsic value'),
 ('Technical Analyst', 'Reads price, volume and indicators such as MACD and RSI'),
 ('Sentiment Analyst', 'Gauges mood from social media, analyst ratings and options flow'),
 ('News Analyst', 'Tracks news wires, press releases and macro events'),
 ('Bull / Bear Researchers', 'Argue for and against the trade so weak ideas are challenged'),
 ('Trader', 'Combines the reports into a buy, sell or hold call with timing and size'),
 ('Risk Manager', 'Checks volatility, liquidity, exposure and drawdown limits'),
 ('Portfolio Manager', 'Approves or rejects the proposal and fits it into the whole portfolio'),
 ('Execution Agent', 'Places approved orders through a broker API at the best price'),
 ('Backtest / Evaluation Agent', 'Tests signals on historical data and feeds back improvements'),
 ('Audit / Compliance Agent', 'Logs every decision and checks it against rules and limits')]

AGENT_RISKS = [('Hallucination',
  'An LLM states a wrong earnings figure or invents a signal with confidence',
  'Ground answers in tool or RAG data, log the reasoning, review unusual calls'),
 ('Prompt injection',
  "Malicious text in news, web pages or files hijacks the agent's instructions",
  'Input and output guardrails, least-privilege API keys, no secrets in prompts'),
 ('Overtrading and runaway loops',
  'Agents trade too often or amplify each other, compounding losses',
  'Order and position caps, daily-loss circuit breaker, kill switch'),
 ('Model and backtest risk',
  'Overfitting, look-ahead bias and regime change: strong backtests, weak live results',
  'Walk-forward tests, paper trade first, monitor drift and costs'),
 ('Accountability',
  "Unclear who answers for an autonomous agent's trade or a vendor's AI",
  'The firm stays accountable: human sign-off, audit trails, clear owners'),
 ('Regulation (MAS)',
  'FEAT principles (2018) and MAS AI Risk Management Guidelines (issued Oct 2026)',
  'Board oversight, AI inventory, materiality assessment and lifecycle controls')]

MULTI_AGENT_TRADING = [('TradingAgents (Xiao et al., 2024)',
  'Simulated stock-trading firm: fundamental, sentiment, news and technical analysts, bull/bear debate, trader, risk '
  'team',
  'https://arxiv.org/abs/2412.20138'),
 ('FinMem (Yu et al., 2023)',
  'LLM trading agent with profiling and layered memory making Buy / Sell / Hold decisions on individual stocks',
  'https://arxiv.org/abs/2311.13743'),
 ('FinAgent (Zhang et al., 2024)',
  'Multimodal agent reading prices, news and chart images, with dual-level reflection; tested on stocks and crypto',
  'https://arxiv.org/abs/2402.18485'),
 ('StockAgent (2024)',
  'LLM investor agents trade a simulated stock market under macro, policy and event shocks; avoids test-set leakage',
  'https://arxiv.org/abs/2407.18957'),
 ('QuantAgent (2025)',
  'Price-driven multi-agent system for high-frequency trading: Indicator, Pattern, Trend and Risk agents',
  'https://arxiv.org/abs/2509.09995'),
 ('AI Hedge Fund (open source)',
  'Investor-persona agents (e.g. Warren Buffett), a risk manager and a portfolio manager decide trades for chosen '
  'tickers',
  'https://github.com/virattt/ai-hedge-fund'),
 ('Agentic Trading Lab (Open-Finance-Lab)',
  'Agent-run stock portfolios with backtests and paper trading through the Alpaca API',
  'https://github.com/Open-Finance-Lab/AgenticTrading')]

TOPICS = [{'no': 1,
  'title': 'Foundations of Quant and Algorithmic Trading: From Thorp to AI Agents',
  'sections': [{'id': '1.1',
                'title': 'Quant Success Stories: What Systematic Trading Has Achieved',
                'bullets': ['Ed Thorp - from blackjack to markets: his fund (Convertible Hedge Associates, 1969; '
                            'Princeton Newport Partners from 1974) is often called the first market-neutral hedge '
                            'fund and earned about 20% a year after fees for two decades by hedging warrants and '
                            'convertibles with probability models.',
                            'Renaissance Technologies - mathematician Jim Simons founded Monemetrics in 1978 '
                            '(renamed 1982). Its Medallion fund (1988) trades purely on mathematical models of '
                            'market data and averaged about 66% a year before fees (about 39% after fees) from 1988 '
                            'to 2018.',
                            'D.E. Shaw - founded in 1988 by computer-science professor David Shaw, a former member '
                            "of Morgan Stanley's quantitative trading group; it builds mathematical models and "
                            'software to exploit market anomalies and manages about US$60-65 billion.',
                            'Man AHL - founded in 1987 as a systematic trend-following futures manager whose '
                            'founders typed historical prices in by hand; it grew into a multi-strategy quant '
                            'business trading momentum models across 800+ markets.',
                            'Two Sigma - founded in 2001, it applies artificial intelligence, machine learning and '
                            'distributed computing to trading, and manages about US$70 billion.',
                            'Quant market makers - Jane Street reported about US$20.5 billion of net trading revenue '
                            'in 2024 and nearly a quarter of primary US-listed ETF activity; Citadel Securities is '
                            'estimated to handle about a quarter of all US equities trading.',
                            'The common thread: a testable hypothesis, clean data, rigorous out-of-sample testing, '
                            'realistic costs and strict risk control - exactly the pipeline this course builds.']},
               {'id': '1.2',
                'title': 'The Evolution of Quant: From Thorp and Renaissance to High-Frequency Trading',
                'bullets': ['Algorithmic trading is the use of a computer program that follows a defined set of '
                            'instructions to generate and execute orders automatically, based on price, timing, '
                            'volume or a mathematical model.',
                            "Foundations (1950s-1970s): Markowitz's 'Portfolio Selection' (1952) measures risk as "
                            "variance; Thorp's 'Beat the Market' (1967) applies probability to hedging; the "
                            'Black-Scholes option formula is published as the CBOE opens in April 1973.',
                            "Factors and program trading (1970s-1980s): Barr Rosenberg's Barra builds multi-factor "
                            'risk models of style, industry and size; computers trade baskets of stocks against new '
                            'index futures. Black Monday (19 October 1987) shows portfolio-insurance program selling '
                            'can deepen a crash.',
                            "Statistical arbitrage (1980s-1990s): Gerry Bamberger and Nunzio Tartaglia's group at "
                            'Morgan Stanley trades pairs of stocks that move together, by rule rather than '
                            "intuition. Alumni and imitators - D.E. Shaw (1988) and Renaissance's Medallion (1988) - "
                            'industrialise many small, market-neutral edges.',
                            'Lessons from failure: Long-Term Capital Management, a highly leveraged relative-value '
                            'fund, lost US$4.6 billion in 1998 and was recapitalised under Federal Reserve '
                            "supervision; in the 'quant quake' of August 2007 crowded quant equity market-neutral "
                            'funds lost heavily in days as positions unwound.',
                            'From quant to high-frequency trading (1996-2010s): electronic order books such as '
                            'Island ECN (1996), decimalisation (2001) and Regulation NMS (2005, in force 2007) '
                            "reward speed. HFT firms co-locate servers at exchanges; Spread Networks' US$300 million "
                            'straight fibre cut about 3 ms off New York-Chicago, and microwave links soon beat it.',
                            "The speed race meets regulation: the 6 May 2010 Flash Crash and Knight Capital's loss "
                            'of more than US$460 million in 45 minutes (2012) lead to kill switches and testing '
                            "rules - MiFID II (2018), the SEC Market Access Rule - and IEX's 350-microsecond 'speed "
                            "bump' exchange (2016). In Singapore, SGX RegCo's Regulatory Guide on Algorithmic "
                            'Trading (2020) sets the expectations.',
                            'Democratisation and AI (2018-present): API-first brokers such as Alpaca (2018) open '
                            'algorithmic stock trading to individuals; machine learning and alternative data widen '
                            'the signal set; LLMs and multi-agent systems now read text and propose trades.']},
               {'id': '1.3',
                'title': 'The Paradigm Shift from Machine Learning to LLMs, and Its Impact on Quant',
                'bullets': ['Classical machine-learning quant works on structured data - prices, volumes, '
                            'fundamentals - with features engineered by the quant (lagged returns, RSI, factor '
                            'scores) and models such as regression, random forests and gradient boosting fitted to '
                            'labelled history.',
                            'The LLM paradigm adds unstructured text - news, filings, earnings-call transcripts, '
                            'research - read directly by a pretrained language model. Lopez-Lira and Tang (2023) '
                            "found that ChatGPT's good / bad scores for news headlines predict next-day stock "
                            'returns, most strongly for small stocks and negative news.',
                            'Finance-specific LLMs: BloombergGPT (March 2023) is a 50-billion-parameter model '
                            'trained with 363 billion tokens of Bloomberg financial data plus general text, aimed at '
                            'sentiment, entity recognition and news classification.',
                            "Automated alpha research: systems such as Alpha-GPT turn a quant's idea in plain "
                            'language into formulaic alpha factors, and AlphaAgent targets alpha decay by steering '
                            'away from crowded, homogeneous factors. Coding agents now draft strategy code and '
                            'backtests that the quant reviews.',
                            "New risks: an LLM may already 'know' what happened in its training period, so in-sample "
                            "backtests can carry look-ahead bias and a 'distraction' effect from what the model "
                            "knows about the company (Glasserman and Lin, 2023). Test only on data after the model's "
                            'knowledge cutoff and anonymise company names.',
                            'Faster crowding: Lopez-Lira and Tang report that the returns to LLM news strategies '
                            'decline as LLM adoption rises - prices become more efficient, so an LLM signal decays '
                            'like any other alpha.',
                            'What does not change: the hypothesis, out-of-sample testing, costs, risk limits and '
                            "human accountability. The quant's role shifts from writing every line of a model to "
                            'specifying, testing and supervising models and agents.']},
               {'id': '1.4',
                'title': 'Agentic AI versus AI Agents in Trading, and Multi-Agent Trading Systems',
                'bullets': ['Agentic AI is the capability of AI to plan and act: it calls tools (market-data and '
                            'broker APIs), uses skills and memory, and follows instructions and guardrails to '
                            "complete multi-step work when it is asked - for example, an LLM that fetches a stock's "
                            'bars and news, checks its memory of past trades and proposes an order within its '
                            'instructions.',
                            'An AI agent is a special class of agentic AI that stands by 24/7 and works all the '
                            'time: it is always on, woken by schedules, events and messages rather than by a prompt, '
                            'and keeps long-term memory across days. Examples: OpenClaw (an open-source, self-hosted '
                            'agent), Hermes Agent (Nous Research, February 2026) and OpenAI Dots (always-on agents '
                            'in ChatGPT, September 2026). In trading, an AI agent is a round-the-clock monitor that '
                            'watches prices and news overnight and proposes paper trades within limits.',
                            'Multi-agent systems are agentic AI with several specialised agents - analysts, '
                            'researchers, a trader and a risk manager - that coordinate, debate and decide; run '
                            'continuously, the same desk becomes an always-on AI agent.',
                            'TradingAgents (Xiao et al., 2024) simulates a stock-trading firm: fundamental, '
                            'sentiment, news and technical analyst agents, bullish and bearish researchers who '
                            'debate, a trader agent and a risk-management team.',
                            'Other stock-trading agent systems: FinMem (2023, an LLM trading agent with layered '
                            'memory making Buy / Sell / Hold decisions), FinAgent (2024, multimodal - prices, news '
                            'and chart images), StockAgent (2024, LLM investors in a simulated stock market), '
                            'QuantAgent (2025, indicator, pattern, trend and risk agents for high-frequency '
                            'trading), the open-source AI Hedge Fund and Agentic Trading Lab, which paper-trades '
                            'through the Alpaca API.',
                            'Agentic systems introduce new failure modes: hallucinated figures, prompt injection '
                            'from news text, over-trading and unclear accountability. Controls: hard risk limits '
                            'coded outside the LLM, paper trading first, a full decision log and a human who '
                            'approves every live order.',
                            "Regulatory context in Singapore: MAS's FEAT principles (2018); the MAS Technology Risk "
                            'Management Guidelines; and the MAS Guidelines on Artificial Intelligence Risk '
                            'Management, issued on 7 October 2026 and effective from 7 October 2027, which require '
                            'AI inventories, materiality assessment and lifecycle controls.']},
               {'id': '1.5',
                'title': 'Forms of Data within Financial Services and Big Data Applications in Trading',
                'bullets': ['Market data: OHLCV bars (open, high, low, close, volume) at timeframes from one minute '
                            'to one month; quotes (best bid and ask); trades (every print); and order-book depth. '
                            "Alpaca's Market Data API serves bars, quotes, trades and news.",
                            'Reference and corporate-action data: symbols, exchanges, trading calendars, splits and '
                            'dividends. Using unadjusted prices across a split creates a false crash in a backtest.',
                            'Fundamental and macroeconomic data: financial statements, ratios (P/E, P/B, ROE), '
                            'earnings; interest rates, inflation and central-bank decisions - the inputs to factor '
                            'models.',
                            'Alternative data: news and social-media sentiment, earnings-call transcripts, web '
                            'traffic, satellite imagery and card spending - increasingly turned into trading signals '
                            'by NLP and LLMs.',
                            'The four Vs of big data in trading: volume (tick data runs to billions of rows), '
                            'velocity (streaming quotes), variety (prices, text, images) and veracity (bad ticks, '
                            'survivorship, restatements).',
                            'Big data applications in trading: tick-level execution analytics and smart order '
                            'routing, cross-asset regime detection, news-driven event trading, sentiment signals, '
                            'intraday risk monitoring, and surveillance of order and trade data for market abuse.']},
               {'id': '1.6',
                'title': 'Developing Hypotheses for Quant and Algorithmic Trading Models',
                'bullets': ['Every trading model starts with a hypothesis: a precise, testable statement about '
                            "market behaviour - not 'buy good stocks' but 'when SPY closes below its lower Bollinger "
                            "Band, its average 5-day forward return exceeds its unconditional 5-day return'.",
                            'A good trading hypothesis states the universe, the signal, the holding period, the '
                            'expected effect and the benchmark, and is written down BEFORE looking at the results - '
                            'otherwise it is curve-fitting.',
                            'Express it as a null hypothesis (H0: no difference) and an alternative (H1: the signal '
                            'earns more than the benchmark), with the test and the significance level chosen in '
                            'advance.',
                            'Economic rationale matters: trend following rests on under-reaction and herding; mean '
                            'reversion on over-reaction and liquidity provision; momentum on slow diffusion of '
                            'information; pairs trading on a stable economic link between two stocks. A pattern with '
                            'no rationale is more likely to be noise.',
                            'The quant model-building steps: frame the hypothesis, collect data, define the target '
                            'and features, split by time, train, validate, test out of sample, then paper trade '
                            'before risking capital.',
                            'Business use cases for data analytics and modelling in trading: signal generation, '
                            'execution cost reduction, portfolio construction, risk forecasting and trade '
                            'surveillance - each with its own success metric.']}]},
 {'no': 2,
  'title': 'Technical Indicators, Trading Strategies and Metrics with TradingView and Alpaca',
  'sections': [{'id': '2.1',
                'title': 'Technical Indicators: Trend, Momentum, Volatility and Volume',
                'bullets': ['Simple Moving Average (SMA): the average close over n bars. Exponential Moving Average '
                            '(EMA): a weighted average with smoothing factor 2/(n+1), reacting faster to recent '
                            'prices. Both are trend indicators.',
                            'Relative Strength Index (RSI): 100 - 100/(1 + RS), where RS is the ratio of average '
                            'gains to average losses over 14 bars (Wilder smoothing). Readings above 70 are '
                            "conventionally 'overbought', below 30 'oversold'.",
                            "MACD: the 12-period EMA minus the 26-period EMA, with a 9-period EMA 'signal line'. A "
                            'MACD cross above its signal line is a momentum buy signal.',
                            'Bollinger Bands: a 20-period SMA plus and minus 2 standard deviations. The bands widen '
                            'in volatile markets and narrow in quiet ones; closes outside the bands feed both '
                            'mean-reversion and breakout strategies.',
                            'Average True Range (ATR): the average of the true range (the largest of high-low, '
                            '|high-previous close| and |low-previous close|). Used to size positions and to set '
                            'volatility-based stops.',
                            'Volume indicators: Volume-Weighted Average Price (VWAP), the benchmark price for '
                            'execution quality, and On-Balance Volume (OBV), which accumulates volume on up days and '
                            'subtracts it on down days.',
                            'Every indicator is a statistical transformation of past prices; none predicts the '
                            'future on its own. Indicators lag, and many are highly correlated with each other - '
                            'adding more rarely adds information.']},
               {'id': '2.2',
                'title': 'Classification of Algorithmic Trading and Quant Algorithms',
                'bullets': ['By purpose, trading algorithms fall into seven families: execution, market making, '
                            'arbitrage, directional (alpha), statistical arbitrage and pairs (hedged), factor and '
                            'portfolio construction, and hedging and risk control.',
                            'Execution algorithms work a large order at low cost and market impact: TWAP slices '
                            "evenly over time; VWAP follows the day's volume curve; percentage-of-volume (POV) "
                            'trades a fixed share of live volume; implementation shortfall minimises cost versus the '
                            'arrival price; iceberg orders show only part of the size; smart order routing chooses '
                            'the venue.',
                            "The SEC's 2010 Concept Release on Equity Market Structure groups high-frequency "
                            'strategies into four types: passive market making (resting bids and offers that provide '
                            'liquidity), arbitrage (pricing inefficiencies between related products, such as an ETF '
                            'and its basket), structural (exploiting structural vulnerabilities, such as stale '
                            'quotes), and directional (short-term positions anticipating an intraday move).',
                            'Directional (alpha) strategies: trend following (moving-average crossover), momentum '
                            '(hold recent winners), breakout (new n-day high), mean reversion (Bollinger Bands, '
                            'RSI(2)) and event or news-driven trading.',
                            'Statistical arbitrage and pairs trading are hedged: long one asset and short a related '
                            'one, so most market moves cancel and the profit comes from the spread reverting (Topic '
                            '3.6).',
                            'By holding period: high-frequency (microseconds to seconds), intraday (minutes to '
                            'hours), swing (days to weeks) and position (weeks to months). By model: rule-based, '
                            'statistical, machine learning, reinforcement learning, and LLM / agentic.',
                            'Matching the algorithm to the hypothesis - and to the right statistical test - is the '
                            'A2 skill: a difference in means needs a t-test or bootstrap, a direction forecast needs '
                            'a classifier, a regime question needs clustering, and a spread needs a cointegration '
                            'test.']},
               {'id': '2.3',
                'title': 'Analytics Platforms and Tools: TradingView versus Alpaca, and Python',
                'bullets': ['TradingView is a charting and strategy-design platform: global markets including SGX, '
                            'built-in indicators, the Pine Script language, the Strategy Tester for backtests, '
                            'alerts and webhooks (webhooks need a paid plan), and a built-in Paper Trading account '
                            "opened from the chart's Trading Panel with your own starting capital and commission.",
                            'Alpaca is an API-first US broker: commission-free US stocks and ETFs, plus options and '
                            'crypto; a free paper-trading account that mirrors the live API; the Trading API '
                            '(account, orders, positions, clock) and the Market Data API (bars, quotes, trades, '
                            'news; the free plan uses the IEX feed); and the official alpaca-py Python SDK.',
                            'The key difference: TradingView is where a strategy is designed, visualised and first '
                            'tested; Alpaca is where a program places and manages orders automatically. TradingView '
                            'has no machine learning and a simplified backtester; Alpaca has no charting or strategy '
                            'tester - you build those in Python.',
                            'Trading hours for automation from Singapore: Alpaca offers 24/5 trading of US stocks (8 '
                            'pm ET Sunday to 8 pm ET Friday) - outside the regular session only limit orders with '
                            'extended hours enabled are accepted, at lower liquidity.',
                            'They work together: a TradingView alert can send a webhook to your server, which places '
                            "the order on Alpaca; and an Alpaca account can be connected in TradingView's trading "
                            'panel to trade from the chart.',
                            'Python - pandas, NumPy, scikit-learn, XGBoost, SciPy, matplotlib and alpaca-py - joins '
                            'them: data handling, machine learning, statistical tests, cost-aware backtests and the '
                            'automation loop.',
                            'API keys are credentials: keep them in environment variables or a .env file, never in '
                            'code you share, and use separate paper and live keys.']},
               {'id': '2.4',
                'title': 'Coding Languages for Algorithms and Signals, and Order Placement',
                'bullets': ["Pine Script v6 (TradingView's language): every script starts with //@version=6 and "
                            'declares indicator() or strategy(). Built-in functions such as ta.ema, ta.rsi, '
                            'ta.crossover and strategy.entry express a signal in a few lines.',
                            'Python: the dominant language for quantitative research - readable, with mature data '
                            'and machine learning libraries. A signal is typically a pandas Series of +1 / 0 / -1 '
                            'aligned to the bar index.',
                            'Other languages: C++ and Java for low-latency execution systems, R for statistics, SQL '
                            'for data stores, and MQL for MetaTrader. LLMs can now draft code in all of them, but '
                            'the developer remains accountable for testing it.',
                            'Order types on Alpaca: market (fill now at the best price), limit (fill only at the '
                            'limit price or better), stop (becomes a market order when the stop is hit), stop-limit, '
                            'and trailing stop.',
                            'Time in force: day, gtc (good till cancelled), opg (market on open), cls (market on '
                            'close), ioc (immediate or cancel) and fok (fill or kill). Order classes: simple, '
                            'bracket (entry with take-profit and stop-loss), OCO and OTO.',
                            'The order lifecycle: new, accepted, partially filled, filled, cancelled, expired or '
                            'rejected. A program must read the order status rather than assume a fill.',
                            'Paper trading simulates fills against real market quotes but cannot model your own '
                            'market impact or queue position - a limitation to remember when comparing paper and '
                            'live results.']},
               {'id': '2.5',
                'title': 'Performance and Risk Metric Definitions',
                'bullets': ['Return metrics: total return; compound annual growth rate CAGR = (ending value / '
                            'starting value)^(1/years) - 1; and the benchmark-relative excess return.',
                            'Risk metrics: annualised volatility = standard deviation of daily returns x sqrt(252); '
                            'maximum drawdown = the largest peak-to-trough fall in the equity curve.',
                            'Risk-adjusted metrics: Sharpe ratio = (mean return - risk-free rate) / standard '
                            'deviation, annualised by sqrt(252); Sortino ratio uses only downside deviation; Calmar '
                            'ratio = CAGR / |maximum drawdown|.',
                            'Trade metrics: number of trades, win rate (% of profitable trades), profit factor '
                            '(gross profit / gross loss), average win and loss, expectancy = win rate x average win '
                            '- loss rate x average loss.',
                            'Activity metrics: exposure (% of time in the market) and turnover (traded value / '
                            'average capital). High turnover multiplies the drag of trading costs.',
                            'Market-relative metrics: beta (sensitivity to the benchmark) and alpha (return not '
                            'explained by beta), estimated by regressing strategy returns on benchmark returns.',
                            'No single metric is enough: report return, risk and cost together, and always against a '
                            'buy-and-hold benchmark for the same period.']}]},
 {'no': 3,
  'title': 'Machine Learning Models, Statistical Modelling and A/B Testing for Trading Signals',
  'sections': [{'id': '3.1',
                'title': 'Types of Statistical Analyses, Data Models, Algorithms and Computational Methods',
                'bullets': ['Descriptive analysis summarises what happened (mean return, volatility, skew, '
                            'correlation); inferential analysis tests whether an effect is real (t-test, bootstrap); '
                            'predictive analysis forecasts (regression, classification); prescriptive analysis '
                            'decides (optimisation).',
                            'Supervised learning learns a mapping from features to a known target - regression for a '
                            "continuous target (tomorrow's return), classification for a category (up or down).",
                            'Unsupervised learning finds structure without a target - clustering (market regimes) '
                            'and dimensionality reduction (PCA of a yield curve or a sector basket).',
                            'Reinforcement learning learns a policy from rewards by interacting with an environment '
                            '- used in research for execution and portfolio allocation, but data-hungry and fragile.',
                            'Advanced computational methods: grid and random search over strategy parameters, Monte '
                            'Carlo simulation and bootstrapping, walk-forward optimisation, and gradient-boosted '
                            'ensembles.',
                            'Strategy search is itself an algorithm: testing many parameter combinations on '
                            'in-sample data and then confirming only the best few out of sample - always counting '
                            'how many combinations were tried.']},
               {'id': '3.2',
                'title': 'Supervised Learning Models for Trading Signals',
                'bullets': ['Target and features: the target is what you predict (next-day direction); the features '
                            'are what you know at prediction time (lagged returns, RSI, MACD, volatility, volume '
                            'change). Any feature using future data is leakage.',
                            'Linear regression predicts a continuous return as a weighted sum of features; logistic '
                            'regression outputs the probability of an up day and is a strong, interpretable '
                            'baseline.',
                            "Naive Bayes applies Bayes' theorem with an independence assumption; fast and "
                            'surprisingly useful for text such as news headlines.',
                            'Decision trees split the data on feature thresholds; random forests average many '
                            'decorrelated trees; XGBoost builds trees sequentially, each correcting the last - '
                            'typically the strongest tabular models.',
                            'Neural networks (multi-layer perceptrons, LSTMs, Transformers) can model non-linear and '
                            'sequential patterns, but need far more data and are easy to overfit on daily prices.',
                            'Evaluation: accuracy, precision, recall, F1 and ROC AUC for classifiers; RMSE and '
                            'R-squared for regressors. In trading, a model is judged finally by its net-of-cost '
                            'strategy performance, not by accuracy alone.',
                            'Turning probabilities into positions: go long when P(up) exceeds a threshold such as '
                            '0.55, stay flat otherwise, and re-train on a rolling window.']},
               {'id': '3.3',
                'title': 'Unsupervised Learning: Clustering and PCA for Market Regimes',
                'bullets': ['K-means clustering partitions observations into k groups by minimising within-cluster '
                            'variance. Applied to rolling return and volatility features it separates calm-bull, '
                            'choppy and stressed market regimes.',
                            'Hierarchical clustering builds a tree (dendrogram) of similarity - used to group '
                            'correlated assets and to build more diversified portfolios.',
                            'Principal Component Analysis (PCA) finds orthogonal combinations that explain the most '
                            "variance. For equities the first component is usually 'the market'; for yield curves "
                            'the first three are level, slope and curvature.',
                            'Always standardise features before clustering or PCA, and choose k with the elbow '
                            'method or silhouette score - then name the clusters by inspecting their average '
                            'characteristics.',
                            'Regime-aware trading: run trend following in trending regimes and mean reversion in '
                            'range-bound ones, or cut position size in the high-volatility regime.',
                            'Clusters found on the whole history use future information; for trading, fit the '
                            'clustering on past data only and assign new observations as they arrive.']},
               {'id': '3.4',
                'title': 'Statistical Modelling Techniques for Financial Time Series',
                'bullets': ['Returns, not prices: model log or simple returns, which are closer to stationary. '
                            'Prices trend and wander; regressions on raw prices produce spurious results.',
                            'Stylised facts of returns: fat tails, volatility clustering, weak autocorrelation of '
                            'returns but strong autocorrelation of absolute returns. Normal-distribution assumptions '
                            'understate tail risk.',
                            'Time-ordered validation: never shuffle a time series. Use a chronological train / '
                            "validation / test split, scikit-learn's TimeSeriesSplit, or walk-forward analysis that "
                            're-fits as time advances.',
                            'Feature engineering: lagged returns, rolling statistics, indicator values, calendar '
                            'effects and cross-asset features - each computed only from data available at the '
                            'decision time.',
                            'Regularisation (L1/L2 penalties, tree depth limits, early stopping) controls '
                            'overfitting; fewer, well-motivated features usually beat many.',
                            'Classical time-series models - autoregression (AR), ARIMA and GARCH for volatility - '
                            'remain useful baselines against which a machine learning model must prove its value.']},
               {'id': '3.5',
                'title': 'A/B Testing Trading Strategies',
                'bullets': ['An A/B test compares variant A (for example a 20/50 crossover) with variant B (a 10/30 '
                            'crossover, or the same rule with an RSI filter) on the same data and period, to decide '
                            'whether B is genuinely better.',
                            'State the hypotheses first: H0 - the mean daily returns (or Sharpe ratios) are equal; '
                            "H1 - variant B's is higher. Choose the significance level (commonly 5%) before running "
                            'the test.',
                            "Tests: Welch's t-test on daily returns; a paired test on the daily return difference; "
                            'and a bootstrap confidence interval for the Sharpe difference, which does not assume '
                            'normality.',
                            'Interpretation: a p-value below 0.05 rejects H0; a confidence interval for the '
                            'difference that excludes zero tells the same story with a size attached. Statistical '
                            'significance is not economic significance - check the effect after costs.',
                            "Multiple testing: trying 100 variants will produce about 5 'significant' results by "
                            'chance. Apply a Bonferroni correction or hold out a final test period.',
                            'Live A/B testing: run both variants side by side in separate paper accounts during '
                            'forward testing to compare them on unseen data.']},
               {'id': '3.6',
                'title': 'Pairs Trading: Statistical Arbitrage as a Hedging Algorithm',
                'bullets': ['Pairs trading holds one stock long and an economically linked stock short, in '
                            'hedge-ratio proportion. Market moves that hit both legs largely cancel, so the position '
                            'is a hedge: its profit or loss comes from the spread between the two, not from the '
                            'direction of the market.',
                            "Origins: pioneered by Gerry Bamberger and developed by Nunzio Tartaglia's quantitative "
                            'group at Morgan Stanley in the 1980s; still used by statistical-arbitrage funds.',
                            'Cointegration, not correlation: two prices are cointegrated when a weighted combination '
                            'of them is stationary. Highly correlated stocks can still drift apart for ever; only a '
                            'cointegrated spread is expected to revert.',
                            'Engle-Granger method: (1) regress log price A on log price B - the slope is the hedge '
                            'ratio and the residual is the spread; (2) run an ADF unit-root test on the residual. A '
                            'test statistic below the Engle-Granger critical value (about -3.34 at 5%) indicates '
                            'cointegration.',
                            'Trading rule: standardise the spread as a z-score over a rolling window; go short the '
                            'spread (short A, long B) when z > +2, long the spread when z < -2, and exit as z '
                            'returns towards 0 (for example |z| < 0.5). Trade both legs on the next bar and charge '
                            'costs on both.',
                            'Evidence: Gatev, Goetzmann and Rouwenhorst (2006) found a simple pairs rule on US '
                            'stocks earned average annualised excess returns of up to 11% from 1962 to 2002; later '
                            'studies find smaller and less consistent profits.',
                            'Risks: the relationship can break (re-test cointegration on a rolling basis), the hedge '
                            'ratio drifts, costs are paid twice, short positions incur borrow costs, and screening '
                            'many pairs creates false discoveries.']}]},
 {'no': 4,
  'title': 'Building an End-to-End Algorithmic Trading Pipeline: Backtest, Forward Test and Performance Analysis',
  'sections': [{'id': '4.1',
                'title': 'Architecture of an End-to-End Algorithmic Trading Pipeline',
                'bullets': ['The pipeline: (1) strategy search and research, (2) data ingestion, (3) signal '
                            'generation, (4) backtest with costs, (5) risk checks, (6) order execution, (7) forward '
                            'test on paper, (8) monitoring, logging and performance reporting.',
                            'Configuration lives outside the code: symbols, parameters, position limits and API keys '
                            'sit in a config file or environment variables, so a change is a reviewed configuration '
                            'change rather than an edit to the logic.',
                            'Pre-trade risk controls: maximum position size, maximum order value, maximum daily '
                            'loss, market-hours check, duplicate-order check and a kill switch that halts all '
                            'trading - the controls regulators require of algorithmic traders.',
                            'Event sources: a scheduled job (every bar), a streaming feed (every quote), or an '
                            'external alert - such as a TradingView alert sent by webhook to your own server, which '
                            'then places the order through Alpaca.',
                            'Agentic extension: analyst agents produce a view, a trader agent proposes an order, and '
                            'a risk-manager agent with hard limits approves or rejects it - the LLM never bypasses '
                            'the coded risk checks.',
                            'Every decision is logged: timestamp, inputs, signal, order request, broker response and '
                            'fill - the audit trail for diagnosing problems and for compliance review.']},
               {'id': '4.2',
                'title': 'Backtesting with Realistic Trading Costs',
                'bullets': ['A backtest replays a strategy on historical data. Vectorised backtests are fast '
                            '(whole-array operations); event-driven backtests replay bar by bar and model orders '
                            'more realistically.',
                            "Execute on the NEXT bar: a signal computed on today's close can only be traded at "
                            "tomorrow's open (or later). Same-bar execution is the commonest source of look-ahead "
                            'bias.',
                            'Trading costs: commission (Alpaca charges none on US equities, but most brokers do), '
                            'the bid-ask spread, slippage and market impact, and regulatory fees on sells (the US '
                            'SEC Section 31 fee and FINRA Trading Activity Fee). Short positions also incur borrow '
                            'costs.',
                            'Model costs explicitly: cost per trade = commission + (half-spread + slippage) x shares '
                            'x price + regulatory fees. Express them in basis points of traded value so they scale '
                            'with turnover.',
                            'Report gross and net results side by side, the cost breakdown, and the break-even cost '
                            '- the cost per trade at which the strategy stops making money.',
                            'A strategy whose edge disappears at 5 to 10 basis points per trade is not tradeable for '
                            'most desks, however good its gross Sharpe ratio looks.']},
               {'id': '4.3',
                'title': 'Forward Testing with Automated Paper Trading',
                'bullets': ['Forward testing (paper trading) runs the strategy in real time on data it has never '
                            'seen, placing simulated orders - the bridge between a backtest and live capital.',
                            'The automated bot loop: wait for the bar to close; fetch the latest bars; compute the '
                            'signal; run the risk checks; compare the target position with the actual position; '
                            'submit the buy or sell order; read the order status; log everything; sleep until the '
                            'next bar.',
                            "Alpaca's market clock (is the market open?) and calendar prevent orders outside trading "
                            'hours; the pattern-day-trader rule applies to paper accounts under USD 25,000 as it '
                            'does to live ones.',
                            'Run the forward test long enough to see a meaningful number of trades - weeks for a '
                            'daily strategy - and compare its fills, slippage and returns with what the backtest '
                            'predicted for the same period.',
                            'Run variants side by side in separate paper accounts as a live A/B test, and only '
                            'promote a strategy to live trading through a documented review.']},
               {'id': '4.4',
                'title': 'Potential Reasons for Unintended Outcomes and How to Diagnose Them',
                'bullets': ['Overfitting: parameters tuned to noise. Signs - a spectacular in-sample Sharpe that '
                            'collapses out of sample, and performance that is very sensitive to small parameter '
                            'changes.',
                            'Look-ahead bias: using information not available at the decision time - same-bar '
                            'execution, centred rolling windows, or features normalised with full-sample statistics.',
                            "Survivorship bias: testing only on today's index members, which excludes the companies "
                            'that failed. Data-snooping bias: reporting the best of many tests without adjustment.',
                            'Cost and execution drag: under-estimated spread and slippage, partial fills and '
                            'rejected orders. Signs - paper or live returns persistently below the backtest by '
                            'roughly the turnover x cost.',
                            'Regime change and concept drift: the market behaves differently from the training '
                            'period (2020 COVID volatility, the 2022 rate-hiking cycle). Monitor rolling performance '
                            'and feature distributions.',
                            'Data and software errors: unadjusted splits, time-zone mismatches, missing bars, '
                            "duplicated orders, and stale positions after a restart. Knight Capital's 2012 loss came "
                            'from obsolete code activated by a deployment error.',
                            'Diagnosis method: reproduce the result, isolate the first step where it diverges from '
                            'expectation (data, signal, order, fill), compare against a benchmark or a known-good '
                            'run, fix, then re-test.']},
               {'id': '4.5',
                'title': 'Performance Analysis, Insights and Reporting',
                'bullets': ['A tearsheet presents the equity curve against the benchmark, the drawdown chart, '
                            'monthly returns, rolling Sharpe ratio, the metrics table and the cost breakdown on one '
                            'page.',
                            'Compare backtest and forward test for the same period: did the live fills, number of '
                            'trades and returns behave as the backtest predicted? Explain every material gap.',
                            'Draw insights, not just numbers: in which regimes did the strategy earn its returns, '
                            'what drove its drawdowns, how sensitive is it to costs and parameters, and how '
                            "correlated is it with the desk's existing book?",
                            'Report for the decision-maker: lead with the recommendation (promote, extend the '
                            'forward test, modify or retire), support it with three or four key figures, and state '
                            'the risks and limitations plainly.',
                            'Keep a model record: hypothesis, data, parameters, test results, version and approval - '
                            'the documentation an investment committee and model-risk reviewer expect.']}]}]

VISUALS = {1: {'concepts': [{'title': 'Forms of Data within Financial Services',
                   'tiles': [{'lead': 'Market data',
                              'caption': 'OHLCV bars, quotes, trades, order-book depth — Alpaca serves bars, quotes, '
                                         'trades, news.'},
                             {'lead': 'Reference & corporate actions',
                              'caption': 'Symbols, calendars, splits, dividends — unadjusted splits fake a crash.'},
                             {'lead': 'Fundamental & macro',
                              'caption': 'Statements, ratios, earnings; rates, inflation, central-bank decisions.'},
                             {'lead': 'Alternative data',
                              'caption': 'News and social sentiment, web traffic, satellite, card spend, ESG.'}]},
                  {'title': 'Big Data in Trading — the Four Vs',
                   'tiles': [{'lead': 'Volume',
                              'caption': 'Tick data runs to billions of rows per year for one exchange.'},
                             {'lead': 'Velocity', 'caption': 'Streaming quotes and news arrive in milliseconds.'},
                             {'lead': 'Variety',
                              'caption': 'Prices, text, images, transcripts — structured and unstructured.'},
                             {'lead': 'Veracity',
                              'caption': 'Bad ticks, survivorship, restatements — verify before you trust.'}]},
                  {'title': 'Big Data Applications',
                   'tiles': [{'lead': 'Execution analytics',
                              'caption': 'Tick and quote data to measure and cut slippage.'},
                             {'lead': 'Sentiment and event trading',
                              'caption': 'News and social text scored by NLP and LLMs.'},
                             {'lead': 'Regime detection',
                              'caption': 'Cross-asset returns clustered into market states.'},
                             {'lead': 'Surveillance and risk',
                              'caption': 'Order and trade data scanned for market abuse; intraday risk.'}]},
                  {'title': 'Data Analytics and Modelling Use Cases',
                   'tiles': [{'lead': 'Signal generation',
                              'caption': 'Find repeatable return — judged by out-of-sample, net Sharpe.'},
                             {'lead': 'Execution',
                              'caption': 'VWAP / TWAP / shortfall — judged by slippage in basis points.'},
                             {'lead': 'Risk forecasting & sizing',
                              'caption': 'Volatility and VaR models — judged by limit breaches.'},
                             {'lead': 'Research at scale',
                              'caption': 'LLMs read filings and news — judged by accuracy and hours saved.'}]},
                  {'title': 'What Makes a Hypothesis Testable',
                   'tiles': [{'lead': 'Instrument and universe', 'caption': 'e.g. SPY, daily bars, 2018 – 2025.'},
                             {'lead': 'Signal and holding period',
                              'caption': 'e.g. three down closes in a row; hold 5 days.'},
                             {'lead': 'Expected effect and benchmark',
                              'caption': 'Forward return exceeds the unconditional 5-day return.'},
                             {'lead': 'Written BEFORE the test',
                              'caption': 'H0, H1 and the significance level chosen first.'}]}],
     'flows': [{'title': 'Machine Learning Implementation Steps',
                'steps': ['Frame the problem and hypothesis',
                          'Collect and clean the data',
                          'Define target and features',
                          'Split by time; train and validate',
                          'Test out of sample',
                          'Paper trade, then review'],
                'note': 'A model that skips the out-of-sample test and the paper trade has not been tested.'}]},
 2: {'concepts': [{'title': 'Trend and Momentum Indicators',
                   'tiles': [{'lead': 'SMA / EMA',
                              'caption': 'Average close over n bars; EMA weights recent bars by 2/(n+1).'},
                             {'lead': 'MACD',
                              'caption': 'EMA12 − EMA26 with a 9-EMA signal line; crosses flag momentum.'},
                             {'lead': 'RSI (14)',
                              'caption': '100 − 100/(1+RS); above 70 overbought, below 30 oversold.'},
                             {'lead': 'Donchian channel',
                              'caption': 'Highest high / lowest low of n bars — the breakout level.'}]},
                  {'title': 'Volatility and Volume Indicators',
                   'tiles': [{'lead': 'Bollinger Bands',
                              'caption': 'SMA20 ± 2 standard deviations; width tracks volatility.'},
                             {'lead': 'ATR (14)',
                              'caption': 'Average true range — position sizing and volatility stops.'},
                             {'lead': 'VWAP', 'caption': 'Volume-weighted average price — the execution benchmark.'},
                             {'lead': 'OBV', 'caption': 'Adds volume on up days, subtracts on down days.'}]},
                  {'title': 'Matching the Method to the Hypothesis',
                   'tiles': [{'lead': "'Does the signal beat the benchmark?'",
                              'caption': 'Backtest + t-test or bootstrap on returns.'},
                             {'lead': "'Will tomorrow be up?'",
                              'caption': 'Classifier: logistic regression, random forest, XGBoost.'},
                             {'lead': "'What state is the market in?'",
                              'caption': 'Clustering: K-means on return and volatility features.'},
                             {'lead': "'Which parameters?'",
                              'caption': 'Grid search in-sample, confirm out-of-sample.'}]},
                  {'title': 'Coding Languages for Algorithms and Signals',
                   'tiles': [{'lead': 'Pine Script v6',
                              'caption': '//@version=6 · ta.ema · ta.crossover · strategy.entry.'},
                             {'lead': 'Python',
                              'caption': 'Signals as pandas Series of +1 / 0 / −1 aligned to bars.'},
                             {'lead': 'C++ / Java',
                              'caption': 'Low-latency execution engines and exchange gateways.'},
                             {'lead': 'R, SQL, MQL',
                              'caption': 'Statistics, data stores, MetaTrader expert advisors.'}]},
                  {'title': 'Order Types and Time in Force',
                   'tiles': [{'lead': 'Market and limit', 'caption': 'Certainty of fill versus control of price.'},
                             {'lead': 'Stop, stop-limit, trailing stop',
                              'caption': 'Trigger on a price; protect or enter on breaks.'},
                             {'lead': 'Bracket / OCO / OTO',
                              'caption': 'Entry with attached take-profit and stop-loss.'},
                             {'lead': 'day · gtc · opg · cls · ioc · fok',
                              'caption': 'How long an order stays working.'}]},
                  {'title': 'Performance and Risk Metrics',
                   'tiles': [{'lead': 'Return', 'caption': 'Total return · CAGR = (end/start)^(1/years) − 1.'},
                             {'lead': 'Risk', 'caption': 'Volatility = σ(daily) × √252 · maximum drawdown.'},
                             {'lead': 'Risk-adjusted', 'caption': 'Sharpe · Sortino · Calmar = CAGR / |MaxDD|.'},
                             {'lead': 'Trade quality',
                              'caption': 'Win rate · profit factor · expectancy · turnover · exposure.'}]}],
     'flows': [{'title': 'The Order Lifecycle',
                'steps': ['new', 'accepted', 'partially filled', 'filled', 'cancelled / expired / rejected'],
                'note': 'Bracket orders protect a position even if your program stops running.'},
               {'title': 'From Idea to Tested Rule on TradingView',
                'steps': ['Chart the instrument and timeframe',
                          'Add indicators (Pine)',
                          'Write the strategy() script',
                          'Set commission and slippage',
                          'Read the Strategy Tester',
                          'Compare with buy-and-hold'],
                'note': 'The Strategy Tester is a first filter; the full test with costs runs in Python.'}]},
 3: {'concepts': [{'title': 'Types of Statistical Analyses',
                   'tiles': [{'lead': 'Descriptive',
                              'caption': 'What happened — mean return, volatility, skew, correlation.'},
                             {'lead': 'Inferential',
                              'caption': 'Is it real? — t-test, bootstrap, confidence intervals.'},
                             {'lead': 'Predictive', 'caption': 'What next? — regression, classification.'},
                             {'lead': 'Prescriptive', 'caption': 'What to do? — optimisation, position sizing.'}]},
                  {'title': 'Families of Learning Algorithms',
                   'tiles': [{'lead': 'Supervised', 'caption': 'Features → known target: up/down, next return.'},
                             {'lead': 'Unsupervised', 'caption': 'Structure without a target: regimes, PCA factors.'},
                             {'lead': 'Reinforcement',
                              'caption': 'Learn a policy from rewards — execution research.'},
                             {'lead': 'Search & simulation',
                              'caption': 'Grid search, Monte Carlo, bootstrap, walk-forward.'}]},
                  {'title': 'Supervised Models for Trading Signals',
                   'tiles': [{'lead': 'Linear / logistic regression',
                              'caption': 'Interpretable baselines; P(up) from a weighted sum.'},
                             {'lead': 'Decision tree & random forest',
                              'caption': 'Threshold splits; averaged trees reduce variance.'},
                             {'lead': 'XGBoost',
                              'caption': 'Sequential boosted trees — strongest on tabular features.'},
                             {'lead': 'Neural networks',
                              'caption': 'MLP, LSTM, Transformer — data-hungry, easy to overfit.'}]},
                  {'title': 'Unsupervised Models for Regimes',
                   'tiles': [{'lead': 'K-means',
                              'caption': 'Minimise within-cluster variance; choose k by elbow or silhouette.'},
                             {'lead': 'Hierarchical clustering',
                              'caption': 'Dendrogram of similar assets for diversification.'},
                             {'lead': 'PCA',
                              'caption': 'First component ≈ the market; yield curve = level, slope, curvature.'},
                             {'lead': 'Fit on the past only',
                              'caption': 'Assign new days to regimes as they arrive.'}]},
                  {'title': 'Statistical Modelling Techniques',
                   'tiles': [{'lead': 'Returns, not prices',
                              'caption': 'Closer to stationary; avoids spurious regression.'},
                             {'lead': 'Time-ordered validation',
                              'caption': 'TimeSeriesSplit and walk-forward — never shuffle.'},
                             {'lead': 'Leak-free features',
                              'caption': 'Lags and rolling windows known at decision time.'},
                             {'lead': 'Regularise',
                              'caption': 'L1/L2, depth limits, early stopping, fewer features.'}]},
                  {'title': 'A/B Testing Two Strategy Variants',
                   'tiles': [{'lead': 'State H0 and H1 first',
                              'caption': 'H0: equal mean returns; H1: B is higher. α = 5%.'},
                             {'lead': "Welch's t-test",
                              'caption': 'Compare mean daily returns with unequal variances.'},
                             {'lead': 'Bootstrap the Sharpe difference',
                              'caption': 'Resample returns; 95% CI excluding 0?'},
                             {'lead': 'Mind multiple testing',
                              'caption': "100 variants → ~5 false 'winners' by chance."}]}],
     'flows': [{'title': 'From Probability to Position',
                'steps': ['Build leak-free features',
                          'Train on past window',
                          'Predict P(up) for tomorrow',
                          'Long if P(up) > 0.55, else flat',
                          'Backtest net of costs'],
                'note': 'Judge the model by the net-of-cost strategy, not by accuracy alone.'}]},
 4: {'concepts': [{'title': 'Pre-Trade Risk Controls',
                   'tiles': [{'lead': 'Position and order limits',
                              'caption': 'Maximum shares, maximum order value per symbol.'},
                             {'lead': 'Maximum daily loss', 'caption': 'Stop trading for the day when breached.'},
                             {'lead': 'Market-hours and duplicate checks',
                              'caption': 'Alpaca clock; never resend an open order.'},
                             {'lead': 'Kill switch', 'caption': 'One file or flag halts all trading immediately.'}]},
                  {'title': 'Trading Costs You Must Model',
                   'tiles': [{'lead': 'Commission', 'caption': 'Zero on Alpaca US equities — not on most brokers.'},
                             {'lead': 'Spread and slippage',
                              'caption': 'Half-spread + slippage on every fill, in bps.'},
                             {'lead': 'Regulatory fees on sells', 'caption': 'SEC Section 31 fee and FINRA TAF.'},
                             {'lead': 'Borrow and impact',
                              'caption': 'Short-borrow costs; your own market impact.'}]},
                  {'title': 'Potential Reasons for Unintended Outcomes',
                   'tiles': [{'lead': 'Overfitting and data snooping',
                              'caption': 'Great in-sample, collapses out of sample.'},
                             {'lead': 'Look-ahead and survivorship bias',
                              'caption': "Same-bar fills; only today's survivors."},
                             {'lead': 'Cost and execution drag',
                              'caption': 'Live returns trail the backtest by turnover × cost.'},
                             {'lead': 'Regime change, data and code errors',
                              'caption': 'Drift, bad splits, time zones, duplicate orders.'}]},
                  {'title': 'What Goes on a Tearsheet',
                   'tiles': [{'lead': 'Equity versus benchmark',
                              'caption': 'Growth of USD 100,000, strategy and buy-and-hold.'},
                             {'lead': 'Drawdown and rolling Sharpe',
                              'caption': 'Depth, length and stability of the edge.'},
                             {'lead': 'Monthly returns heatmap', 'caption': 'When did it make — and lose — money?'},
                             {'lead': 'Metrics and cost table',
                              'caption': 'Gross versus net; backtest versus forward.'}]}],
     'flows': [{'title': 'The End-to-End Algorithmic Trading Pipeline',
                'steps': ['Strategy search',
                          'Data ingestion',
                          'Signal',
                          'Backtest with costs',
                          'Risk checks',
                          'Order execution',
                          'Forward test',
                          'Monitor and report'],
                'note': 'Configuration — symbols, parameters, limits, keys — lives outside the code.'},
               {'title': 'The Automated Paper-Trading Bot Loop',
                'steps': ['Bar closes',
                          'Fetch latest bars',
                          'Compute signal',
                          'Run risk checks',
                          'Target vs actual position',
                          'Submit order; read status',
                          'Log and sleep'],
                'note': 'Every cycle writes to the trade log — the evidence for performance and audit.'},
               {'title': 'TradingView Alert to Alpaca Order',
                'steps': ['Pine strategy fires alert',
                          'TradingView POSTs JSON',
                          'Your server checks secret',
                          'Risk checks',
                          'alpaca-py submits paper order',
                          'Log and respond 200'],
                'note': 'Webhook alerts need a paid TradingView plan and a public URL (e.g. a tunnel).'},
               {'title': 'Diagnosing an Unintended Outcome',
                'steps': ['Reproduce the result',
                          'Isolate the first divergent step',
                          'Data · signal · order · fill?',
                          'Compare with a known-good run',
                          'Fix and re-test'],
                'note': 'Read the first failure, not the last — everything after it is a consequence.'}]}}
