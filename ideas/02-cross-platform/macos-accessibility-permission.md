# macOS Accessibility permission UX

## Problem

CGEvent injection silently fails until the user grants Accessibility. First-run users will say "the typing doesn't work" and uninstall.

## Solution

Implementation detail covered in [macos-cgevent-injector](macos-cgevent-injector.md). Pulled out here because the *UX* is its own thing:

1. On macOS startup, call `AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: true})`. macOS shows its own dialog if needed.
2. If still untrusted after the dialog closes, show a Wispr-branded panel with:
   - Screenshot of the right System Settings page.
   - A "Open System Settings" button (`subprocess.run(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"])`).
   - A "Test typing" button that becomes enabled once trust is granted, with a target field to type into.
3. Re-poll trust state every 2 s while the panel is open so it auto-advances when the user grants.

## Effort

Small — one panel, one polling timer.
