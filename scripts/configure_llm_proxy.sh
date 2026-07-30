#!/usr/bin/env bash
set -euo pipefail

output_path="${HOME}/.config/robotraceopt/llm_proxy.env"
if [[ $# -gt 0 ]]; then
  if [[ $# -ne 2 || "$1" != "--output" ]]; then
    echo "Usage: $0 [--output PATH]" >&2
    exit 2
  fi
  output_path="$2"
fi

read -r -p "OpenAI-compatible API base (ending in /v1): " api_base
read -r -p "Model name exposed by the proxy: " model
read -r -p "API style [chat_completions/responses] (default chat_completions): " api_style
api_style="${api_style:-chat_completions}"
read -r -s -p "API key (input hidden): " api_key
printf '\n'

if [[ ! "${api_base}" =~ ^https?://[^[:space:]]+$ ]]; then
  echo "API base must be an http:// or https:// URL without spaces." >&2
  exit 2
fi
if [[ -z "${model}" || "${model}" == *$'\n'* || "${model}" == *$'\r'* ]]; then
  echo "Model name must be non-empty and single-line." >&2
  exit 2
fi
if [[ "${api_style}" != "chat_completions" && "${api_style}" != "responses" ]]; then
  echo "API style must be chat_completions or responses." >&2
  exit 2
fi
if [[ -z "${api_key}" || "${api_key}" == *$'\n'* || "${api_key}" == *$'\r'* ]]; then
  echo "API key must be non-empty and single-line." >&2
  exit 2
fi

output_dir="$(dirname "${output_path}")"
mkdir -p "${output_dir}"
chmod 700 "${output_dir}"
temporary="$(mktemp "${output_dir}/.llm_proxy.env.XXXXXX")"
trap 'rm -f -- "${temporary}"' EXIT
chmod 600 "${temporary}"
{
  printf 'export LLM_API_BASE=%q\n' "${api_base%/}"
  printf 'export LLM_MODEL=%q\n' "${model}"
  printf 'export LLM_API_STYLE=%q\n' "${api_style}"
  printf 'export LLM_API_KEY=%q\n' "${api_key}"
} > "${temporary}"
mv -f -- "${temporary}" "${output_path}"
trap - EXIT
unset api_key

echo "Proxy configuration written with mode 0600: ${output_path}"
echo "Load it with: source ${output_path}"
