# Setting Up Clerk

Complete guides for installing and configuring Clerk on your platform.

```{toctree}
:maxdepth: 1
:caption: Setup Guides

prerequisites
macos
linux
single-machine
distributed
verification
troubleshooting
```

## Quick Navigation

**Choose your platform:**
- [macOS Setup](macos.md) - Complete setup for macOS systems
- [Linux Setup](linux.md) - Complete setup for Linux systems

**Worker Configuration:**
- [Single-Machine Setup](single-machine.md) - Run all workers on one machine
- [Distributed Setup](distributed.md) - Scale across multiple machines

**Additional Resources:**
- [Prerequisites](prerequisites.md) - System requirements
- [Verification](verification.md) - Confirm your setup works
- [Troubleshooting](troubleshooting.md) - Common setup issues

## Setup Flow

1. **Review Prerequisites** - Check system requirements
2. **Platform Installation** - Install Clerk and dependencies for your OS
3. **Worker Configuration** - Configure task queue workers
4. **Verification** - Run end-to-end tests
5. **Troubleshooting** (if needed) - Fix common issues

## Quick Start Decision Tree

```
┌─ Which platform? ───────────────────────────┐
│                                              │
├─ macOS ──> [macOS Setup](macos.md)         │
│                                              │
├─ Linux ──> [Linux Setup](linux.md)         │
│                                              │
└──────────────────────────────────────────────┘

┌─ How many machines? ─────────────────────────┐
│                                              │
├─ One ──> [Single-Machine](single-machine.md)│
│                                              │
├─ Multiple ──> [Distributed](distributed.md) │
│                                              │
└──────────────────────────────────────────────┘
```

## Next Steps

After completing setup, see:
- [Operations Guide](../operations/index.md) - Day-to-day maintenance
- [Your First Site Tutorial](../guides/first-site.md) - Complete walkthrough
