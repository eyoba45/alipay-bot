
#!/bin/bash

echo "===== GitHub Repository Setup ====="
echo "This script will help you connect to GitHub."

# Configure Git
echo "Setting up Git credentials..."
read -p "Enter your GitHub username: " GIT_USERNAME
read -p "Enter your GitHub email: " GIT_EMAIL

git config --global user.name "$GIT_USERNAME"
git config --global user.email "$GIT_EMAIL"

# Remove any existing remote
git remote remove origin 2>/dev/null

# Add new GitHub repository
read -p "Enter your GitHub repository URL (https://github.com/username/repo): " REPO_URL

if [[ -z "$REPO_URL" ]]; then
  echo "Error: Repository URL cannot be empty"
  exit 1
fi

git remote add origin "$REPO_URL"

echo "Testing connection to GitHub..."
git fetch origin --dry-run

if [ $? -eq 0 ]; then
  echo "✅ Connection to GitHub successful!"
  echo ""
  echo "To push your code to GitHub, run:"
  echo "git add ."
  echo "git commit -m \"Your commit message\""
  echo "git push -u origin main"
else
  echo "❌ Connection to GitHub failed."
  echo ""
  echo "Please make sure:"
  echo "1. You have connected your Replit account to GitHub (Account → Connected Services)"
  echo "2. You have entered the correct repository URL"
  echo "3. You have the correct permissions for the repository"
fi
