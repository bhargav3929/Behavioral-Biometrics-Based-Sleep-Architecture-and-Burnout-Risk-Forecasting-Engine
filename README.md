# Behavioral Biometrics Based Sleep Architecture and Burnout Risk Forecasting Engine

You log seven days of sleep, bedtime and wake time, screen hours and caffeine. The app turns that log into a **burnout risk score from 0 to 100**, shows where your recovery is leaking (sleep debt, late caffeine, screen light, an erratic body clock), and writes an **hour-by-hour recovery schedule** for tomorrow. It is built for students, shift workers, parents and anyone who feels tired all the time and wants to know why.

> **Wellness and education only. This is not medical advice.** It does not diagnose sleep disorders or any medical condition. See a doctor for persistent insomnia or exhaustion.

## 1. What you need

- **Python 3.10 or newer.** Download it from https://www.python.org/downloads/ (on Windows, tick "Add python.exe to PATH" during install).
- **A free Groq key** from https://console.groq.com/keys. It takes about one minute and needs no card.
- An internet connection for the first start (to install packages) and for each AI forecast.

## 2. Run it (one command)

- **macOS / Linux:** `chmod +x start.sh && ./start.sh`
- **Windows:** double-click `start.bat`

The first run sets up a private environment, installs the packages and creates your `.env` file. Your browser then opens at **http://127.0.0.1:8010**. Next time it starts in a few seconds.

## 3. Add your Groq key

Either:

- Click **API Keys** in the app, paste your key (it starts with `gsk_`) and press **Save key**, or
- Open `.env` and set `GROQ_API_KEY=gsk_your_key_here`, then restart.

The key stays on your computer. The app only ever shows it masked, like `gsk_...ab12`.

## 4. How to use it

1. Click a sample log under **Sample logs** on the left, for example **Tech crunch week**. Its saved result appears instantly and uses none of your runs.
2. Look at the gauge, the four health tiles, the alerts and the chart. Open **Chronobiology Formula and Biometric Verification Audit** to check every calculation by hand.
3. Click **Daily Recovery Schedule** in the left menu for the hour-by-hour plan. The same timeline also sits at the bottom of the forecast.
4. Now use your own week. Edit the table (or paste a CSV into **Paste 7-Day CSV / Log**), pick the context that fits you (for example **Teenager / Adolescent** or **Pregnant / Postpartum**, or choose **Custom Context...** and describe yourself), then press the glowing **Forecast Burnout & Build Recovery Plan** button.
5. Click **What-If Recovery Simulator** in the left menu to try one change, such as an earlier caffeine cutoff, and see the before and after.
6. The **History** button in the left menu lists your earlier forecasts. You get 15 live runs per hour. A run that fails is never counted.

If your log is impossible (for example 16 hours of sleep and 14 hours of screen time in one day) the app rejects it and tells you which day to fix. Nothing is scored and no run is used.

## 5. How it works

1. **Check the log** (`app/chronobiology.py`). 7 to 14 days, no negative numbers, no day over 24 hours, caffeine of 1,200 mg or less, valid 24-hour clock times, and not all zeros.
2. **Read your context** (`app/chronobiology.py`). Your pill choice and any free text set your sleep baseline and caffeine ceiling: teenagers 9 h and 100 mg, pregnancy 200 mg, everyone else 8 h and 400 mg (adjustable in `.env`).
3. **Compute the numbers** (`app/chronobiology.py`). Cumulative sleep debt, caffeine still active at bedtime (5-hour half-life), how much your sleep midpoint wobbles, deep/REM efficiency, and a weighted burnout score. Safety rules catch traps such as weekend binge sleep, 11 hours of sleep with 10 hours of screens, and "7 hours" of sleep ruined by late caffeine, so those never read as "optimal".
4. **Ask the AI coach** (`app/ai_groq.py`, `app/forecast.py`). Groq receives your finished numbers and writes the plain-English explanation, the root causes and the daily schedule. It cannot change the score. The module retries when Groq is busy and switches to the backup model if needed.
5. **Serve and store** (`app/main.py`, `app/db.py`, `app/access.py`). FastAPI serves the page in `static/` (`index.html`, `styles.css`, `js/`) and keeps your history, saved key and the hourly run counter in a local SQLite file under `data/`.

Bundled sample logs live in `samples/`, and their saved results in `samples/results/`.

## 6. Project structure

```
10_sleep_architecture_burnout_forecasting/
├── .env.example            settings template (copied to .env on first run)
├── .gitattributes          keeps line endings correct for the start scripts
├── .gitignore              keeps .env, .venv, data/ and databases out of git
├── README.md
├── requirements.txt
├── start.bat               Windows one-command start
├── start.sh                macOS / Linux one-command start
├── app/
│   ├── __init__.py
│   ├── access.py           who may change keys and how runs are limited
│   ├── ai_groq.py          the only file that talks to Groq
│   ├── chronobiology.py    validation, guardrails and all the math
│   ├── config.py           reads settings from .env
│   ├── db.py               SQLite storage
│   ├── errors.py           one error format for every route
│   ├── forecast.py         combines the math with the AI coach
│   └── main.py             FastAPI routes
├── samples/
│   ├── balanced-circadian-baseline.csv
│   ├── invalid-biometric-log-control.csv
│   ├── social-jetlag-late-caffeine.csv
│   ├── tech-crunch-burnout-week.csv
│   └── results/            saved real results, one JSON per sample
├── scripts/
│   └── record_samples.py   re-records the saved sample results
└── static/
    ├── index.html
    ├── styles.css
    └── js/
        ├── app.js          buttons, table and server calls
        ├── charts.js       burnout gauge, sleep and caffeine wave chart
        └── render.js       builds the result panels
```

The folders `.venv/` and `data/` and the file `.env` are created on your computer when you run the app. They are not part of the download.

## 7. Troubleshooting

- **"Port already in use".** Another program is using port 8010. Close it, or change `PORT=` in `.env` and restart (then open that port instead).
- **"The AI service is busy right now".** Groq's free tier is crowded. The app already retried and tried a backup model. Wait a minute and press run again. That attempt did not use up a run.
- **"Your Groq key was rejected".** The key is wrong, expired or has a space in it. Make a new one at https://console.groq.com/keys and paste it under **API Keys**.
- **"No Groq key is set up yet".** Open **API Keys** and paste your key. Sample logs work without a key.
- **Python not found.** Install Python 3.10 or newer from https://www.python.org/downloads/ (tick "Add python.exe to PATH" on Windows), then run the start script again.
- **Install failed on a slow connection.** Check your internet and run the start script again. It continues where it stopped.
- **The browser did not open.** Open http://127.0.0.1:8010 yourself while the start window is still running.
