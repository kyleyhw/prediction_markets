#!/usr/bin/env bash
# Run your own copy of vibe-predict on this computer, with the model you
# choose (docs/tutorials/run_your_own.md). Needs Docker and nothing else.
#
#   ./deploy/run-your-own.sh          # first time: asks a few questions
#   ./deploy/run-your-own.sh stop     # stop it (your data stays)
#
# Your answers go in deploy/.env, which stays on this computer; run the
# script again to start the copy with them, or delete the file to choose
# again.
set -euo pipefail
cd "$(dirname "$0")"
ENV=.env
COMPOSE=(docker compose --env-file "$ENV" -f compose.yaml)

if ! docker info >/dev/null 2>&1; then
  echo "Docker is not running. Install Docker Desktop (docker.com), start it, and run this again."
  exit 1
fi

if [ "${1:-}" = "stop" ]; then
  "${COMPOSE[@]}" down
  echo "Stopped. Your data is kept; run ./deploy/run-your-own.sh to start again."
  exit 0
fi

if [ ! -f "$ENV" ]; then
  echo "Which model should answer in your copy?"
  echo "  1) A free model on this computer, through Ollama (ollama.com)"
  echo "  2) A provider's model, with your own key (Anthropic, Google, OpenAI, Groq, OpenRouter...)"
  echo "  3) A program of your own (start from examples/my_model.py)"
  read -rp "1, 2 or 3: " choice
  case "$choice" in
    1)
      read -rp "Ollama model name [qwen2.5:7b]: " model
      model=${model:-qwen2.5:7b}
      echo "Make sure Ollama is running and has the model: ollama pull $model"
      lines="VP_DEMO_PROVIDER=custom
VP_DEMO_MODEL=$model
VP_DEMO_BASE_URL=http://host.docker.internal:11434/v1
VP_DEMO_FREE=true"
      ;;
    2)
      read -rp "Provider (anthropic, gemini, openai, groq, openrouter, mistral, deepseek, together, xai): " provider
      read -rp "Model name, as the provider writes it: " model
      read -rsp "Key (not shown): " key; echo
      lines="VP_DEMO_PROVIDER=$provider
VP_DEMO_MODEL=$model
VP_DEMO_API_KEY=$key
VP_DEMO_FREE=false"
      ;;
    3)
      read -rp "Program file in examples/ [my_model.py]: " program
      lines="VP_DEMO_PROVIDER=command
VP_DEMO_MODEL=my-model
VP_DEMO_BASE_URL=python /models/${program:-my_model.py}
VP_DEMO_FREE=true"
      ;;
    *) echo "Please answer 1, 2 or 3."; exit 1 ;;
  esac
  master=$(head -c 32 /dev/urandom | base64)
  umask 077
  cat > "$ENV" <<EOF
# Your own copy's settings (deploy/run-your-own.sh). Keep this file private.
VP_MASTER_KEY=$master
VP_SHOW_SIGN_IN_LINK=true
VP_WEB_WORKERS=1
$lines
EOF
  echo "Saved your choices in deploy/.env."
fi

echo "Building the app (the first time takes a few minutes)..."
docker build -q -t vibe-predict:dev .. >/dev/null
"${COMPOSE[@]}" up -d
echo
echo "Your copy is starting. In a minute, open http://localhost:8000 and sign in"
echo "with any email address: on your own copy the sign-in link is shown on the page."
echo "Market data arrives over the next few minutes. Stop it with: ./deploy/run-your-own.sh stop"
