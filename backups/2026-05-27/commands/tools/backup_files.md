---
description: Backup ~/.claude/commands and claude_projects Python helpers to GitHub (claude_backup repo), rotating to keep 4 snapshots
---

Backup skill definitions and Python helper modules to the `claude_backup` GitHub repo.

# Config
- Commands: `/Users/macproajb/.claude/commands`
- Helpers: `/Users/macproajb/claude_projects` (`.py` + `requirements.txt` only)
- Utils: `/Users/macproajb/.claude/utils` (`.py` only)
- Local repo: `~/claude_backup`
- Remote: `git@github.com:DataVizHonduran/claude_backup.git`
- Max snapshots: 4

# Steps

## Step 1: Ensure local repo exists
```bash
if [ ! -d "$HOME/claude_backup/.git" ]; then
  git clone git@github.com:DataVizHonduran/claude_backup.git "$HOME/claude_backup"
fi
```

## Step 2: Pull latest
```bash
cd "$HOME/claude_backup" && git pull --rebase
```

## Step 3: Copy files into dated snapshot
```bash
DATE=$(date +%Y-%m-%d)

# Skill definitions (.md files)
mkdir -p "$HOME/claude_backup/backups/$DATE/commands"
rsync -a /Users/macproajb/.claude/commands/ "$HOME/claude_backup/backups/$DATE/commands/"

# Python helper modules — source only, no outputs or secrets
mkdir -p "$HOME/claude_backup/backups/$DATE/helpers"
rsync -a --include="*/" --include="*.py" --include="requirements.txt" --exclude="*" \
  /Users/macproajb/claude_projects/ "$HOME/claude_backup/backups/$DATE/helpers/"

# .claude/utils Python files
mkdir -p "$HOME/claude_backup/backups/$DATE/helpers/utils"
rsync -a --include="*.py" --exclude="*" \
  /Users/macproajb/.claude/utils/ "$HOME/claude_backup/backups/$DATE/helpers/utils/"

# Clean up artifacts
find "$HOME/claude_backup/backups/$DATE" -name ".DS_Store" -delete
find "$HOME/claude_backup/backups/$DATE" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
```

## Step 4: Rotate — drop oldest if more than 4 snapshots
```bash
cd "$HOME/claude_backup"
BACKUPS=($(ls -d backups/*/ 2>/dev/null | sort))
while [ ${#BACKUPS[@]} -gt 4 ]; do
  OLDEST="${BACKUPS[0]}"
  echo "Removing oldest snapshot: $OLDEST"
  git rm -rf "$OLDEST"
  BACKUPS=("${BACKUPS[@]:1}")
done
```

## Step 5: Commit and push
```bash
cd "$HOME/claude_backup"
DATE=$(date +%Y-%m-%d)
git add backups/
git diff --staged --quiet && echo "No changes to backup." && exit 0
git commit -m "backup: $DATE"
git push
```

After each step, check exit code. If any step fails, report the error and stop. On success, report the snapshot date and current backup count.
