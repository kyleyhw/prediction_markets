# Run Your Own Copy, With Your Own Model

The app's free demo model cannot serve everyone: it runs on Google's free
tier, which may not be used for people in the European Economic Area,
Switzerland or the United Kingdom, or in countries Google does not serve.
If the app told you the demo model is not available where you are, you
have two ways to carry on, and both are free if you want them to be.

1. **Connect your own model** in the app: Settings, *Your AI model*. Pick
   the provider, type the model's name and paste your key. Any provider
   works, and several have free plans of their own.
2. **Run your own copy** of the app on your computer, with any model,
   including a free one that runs on the computer itself, or a program you
   write. This page shows how. It takes about half an hour the first
   time. You write no code, but you do install one program (Docker) and
   type two short commands into a terminal; each step below says exactly
   what to type.

Your copy is the same app, with the same pages. It is yours: it runs only
on your computer, nobody else can reach it, and nothing you do in it is
sent anywhere except to the model you choose and to the market data
sources.

## What you need

- A computer with about 10 GB free and 8 GB of memory (16 GB if the model
  runs on the computer too).
- **Docker Desktop**, free from docker.com. Install it and start it; it
  runs the app.
- On Windows, the script below runs in **Git Bash** (comes with Git for
  Windows) or in WSL.

## 1. Get the app

Download it as one file:
<https://github.com/kyleyhw/prediction_markets/archive/refs/heads/master.zip>,
and unzip it (double-click the file). You get a folder called
`prediction_markets-master`. (If you use GitHub, *Fork* the project
instead, so you can keep your own changes.)

**Opening a terminal in that folder.** On a Mac, right-click the folder
in Finder and choose *Services → New Terminal at Folder*. On Windows, open the folder, right-click in an
empty part of it and choose *Open Git Bash here* (Git for Windows adds
it). A terminal is a window where you type a command and press Enter.

## 2. Choose a model

Pick one before you start:

- **A free model on your computer.** Install Ollama from ollama.com (an
  ordinary installer), then in a terminal type `ollama pull qwen2.5:7b`
  and press Enter; it downloads the model, about 5 GB. Larger models answer better
  and need more memory; the 7b model is a good start.
- **A provider's model.** Get a key from the provider's website
  (Anthropic, Google, OpenAI, Groq, OpenRouter, Mistral and others). Some
  have free plans; the key's use is billed by the provider otherwise.
- **A program of your own.** `examples/my_model.py` is a working one: a
  simple rule that forecasts a match from each team's recent results.
  Copy it and change the rule. The strategy assistant and the research
  assistant need a language model to talk to, so a rule answers forecasts
  only.

## 3. Start it

Open a terminal in the folder you unzipped and type:

```bash
./deploy/run-your-own.sh
```

It asks which model you chose (1, 2 or 3) and the details, saves your
answers in `deploy/.env` on your computer, builds the app and starts it.
The first time takes a few minutes.

## 4. Use it

Open <http://localhost:8000>. Sign in with any email address: your copy
has no mail server, so the sign-in link is shown on the page. Market data
arrives over the next few minutes; the guided start explains the rest,
and the [week of tutorials](index.md) works the same in your copy.

To stop it, type `./deploy/run-your-own.sh stop`. Your data is kept for
next time. To choose a different model, delete `deploy/.env` and run the
script again.

## What is different in your copy

- **It starts empty.** The hosted app keeps an archive of evidence
  (weather forecasts as they were issued, news, results); your copy
  collects its own from the moment it starts, so its first backtests have
  less to go on.
- **Its sources' terms are yours.** Your copy fetches market data and
  evidence itself; the free sources it uses are for personal,
  non-commercial use (`docs/evidence.md` lists them).
- **Paper trading only.** Nothing in the app can place a real order.

## If something goes wrong

- *Docker is not running*: start Docker Desktop and run the script again.
- *The model does not answer*: for Ollama, check that it is running and
  that `ollama list` shows the model you named. For a provider, check the
  key and the model's name on the provider's website.
- *The page does not open*: wait a minute after starting; the first start
  sets up the database.
