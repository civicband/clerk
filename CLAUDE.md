# Clerk - Claude Code Instructions

## Git Workflow

**ALWAYS ask about branching strategy before writing any code:**

- Before starting ANY code work, ask: "Should I work on main or create a feature branch?"
- For experimental or significant features → create a feature branch
- For quick fixes or minor changes → may work on main (if user confirms)
- Default assumption: create a feature branch unless explicitly told otherwise
- Consider using `superpowers:using-git-worktrees` for isolated feature work

## Commit Messages

- Do NOT include advertising in commit messages
- Do NOT include "Generated with Claude Code" or similar branding
- Do NOT include Co-Authored-By lines for Claude/AI
- Keep commit messages focused on what the change does
