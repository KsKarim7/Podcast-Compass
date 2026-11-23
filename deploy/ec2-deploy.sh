# Runs on the EC2 instance as root, sent by the deploy job through SSM Run Command.
# The job exports IMAGE, AWS_REGION and KEY_PARAMETER before these lines.
set -euo pipefail

registry="${IMAGE%%/*}"
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$registry"
docker pull "$IMAGE"

# The key is read here, on the instance, so it never appears in the command GitHub sends
# or in either side's logs. It reaches the container through a file only root can read,
# which is deleted when this script exits, whether or not it succeeded.
key=$(aws ssm get-parameter --region "$AWS_REGION" --name "$KEY_PARAMETER" \
  --with-decryption --query Parameter.Value --output text)
env_file=$(mktemp)
trap 'rm -f "$env_file"' EXIT
printf 'GEMINI_API_KEY=%s\n' "$key" > "$env_file"
unset key

docker rm -f podcast-compass >/dev/null 2>&1 || true
docker run -d --name podcast-compass --restart unless-stopped \
  -p 80:8501 --env-file "$env_file" "$IMAGE"

# Old images are no longer used by any container; removing them keeps the small disk free.
docker image prune -af >/dev/null
echo "Running $IMAGE"
