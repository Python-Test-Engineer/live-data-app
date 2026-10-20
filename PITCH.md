Subject: Talk proposal: Building a Data Intelligence AI Agent = LIVE

Hello Brighton Data Intelligence Network organisers,

I'd like to propose a practical talk with a live demo: "Building a Data Intelligence AI Agent = LIVE".

Format: 1 hour - with interaction between us all to develop the application and answer question.

The talk uses real Beryl Brighton bikeshare data. I'll start with a folder of station-level CSV snapshots and show how to turn it into checked evidence and recommendations.

The key design choice: Python does the computing and the AI does the reasoning. Every number in an insight is produced by code and traced to its evidence. The AI explains, connects causes and suggests actions within those numbers, and it states its own limits, such as when there are only a few hours of data.

Part of the talk explains what an AI agent is. Yhis is interwoven with the live building where useful. I'll run a small Python agent that uses tools to read, write and run code in a confined workspace, and walk through the loop: the model picks a tool, the harness runs it, and the result goes back to the model. 

I'll then connect that pattern to the bikeshare analyst, which audits data quality, finds stations that are empty or full, measures net flow between stations and ranks actions by impact and confidence. Forecasts appear only once there is enough history, and only if they beat a simple persistence baseline.

What attendees will take away:
- A working understanding of an agent, and how it differs from a chatbot.
- How raw, time-stamped data becomes checked, ranked findings.
- How to keep AI-written explanations grounded in computed results, and be honest about uncertainty.
- How to design a tool for real decisions rather than another chart.

Audience: mixed data and developer backgrounds. No prior agent experience needed.

Live demo requirements: an internet connection and an OpenRouter API key. I'll have a recorded fallback ready in case the network fails.



Speaker: Craig West - https://craigwestai.com/

Thank you for considering the proposal. I'd be glad to discuss timing or format.

Best,
Craig
