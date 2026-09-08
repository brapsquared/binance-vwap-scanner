# Scheduled advisory runner

`scheduled_runner.py` is the non-trading daily entry point for the scanner. It:

1. calls the existing `scanner.refresh()` workflow, which uses only completed UTC daily candles;
2. sends scanner progress to stderr so it cannot become a digest message;
3. atomically claims refreshed alert IDs through `data/advisory-deliveries.db`;
4. ranks the claimed alerts by empirical continuation probability, sample size, and symbol;
5. writes one concise advisory digest with a stable delivery event ID to stdout, or **zero stdout bytes** when no alert is claimable.

The digest always labels its probability horizon and calibration scope. Perp-only symbols are visibly marked as lower-confidence spot-trained transfers. Output is advisory only: the runner has no account integration, sizing, order, entry, or exit behavior.

## Manual verification

From the repository root:

```text
python scheduled_runner.py
```

Scanner progress and errors go to stderr. A non-empty stdout digest means there are newly emitted alert IDs. Running again against the same accepted alert IDs produces empty stdout.

The runner reads `VELO_API_KEY` through the existing scanner behavior: first from the process environment, then from the default Hermes `.env`. Do not put credentials in this repository or scheduler command arguments.

## Delivery ledger

`data/advisory-deliveries.db` is local generated state and is ignored by Git through the existing `*.db` rule. Before emission, one runner atomically claims each alert ID under a deterministic `daily-advisory:<hash>` event ID distinct from scanner alert IDs. Concurrent runners therefore cannot emit the same active claim. Successful emission acknowledges the event; refreshed alert IDs linked to acknowledged events are not resent.

Claims have a five-minute lease. A failed stdout write releases its claim immediately; a process crash leaves a claim that becomes retryable after the lease. Retries for the same alert set reuse the same event ID, which is printed in the digest for downstream audit or idempotency.

Refresh and alert persistence happen before digest emission. If refresh fails, the command exits non-zero and emits no digest. If writing the digest raises an error, alert IDs remain eligible for retry. Downstream delivery (for example Telegram) is intentionally owned by the scheduler, not by this repository.

The stdout/SQLite acknowledgement boundary is **at-least-once**, not exactly-once: a process or database failure after stdout is written but before acknowledgement can cause the same stable event to be emitted again after its lease expires. Consumers that require stronger suppression should deduplicate on the printed delivery event ID. Hermes maintains its own downstream delivery attempt status separately.

Do not run overlapping copies against the same data directory. For Windows Task Scheduler, select **Do not start a new instance**. Hermes already refuses a manual run while the same job is in flight.

## Windows Task Scheduler example

The trigger must occur after the UTC daily candle closes. Windows schedules in the machine's local time, so convert a target such as `00:15 UTC` to the host's local time and account for daylight-saving changes.

GUI action fields (recommended):

```text
Program/script: C:\path\to\python.exe
Add arguments:  "C:\path\to\binance-vwap-scanner\scheduled_runner.py"
Start in:       C:\path\to\binance-vwap-scanner
```

Set the daily trigger to the local equivalent of `00:15 UTC`, run as the same user that owns the Hermes `.env`, and set **If the task is already running** to **Do not start a new instance**.

Equivalent creation command template (example only; do not run until paths and local time are reviewed):

```bat
schtasks /Create /TN "Binance VWAP Advisory Digest" /SC DAILY /ST 10:15 /TR "C:\Python311\python.exe C:\binance-vwap-scanner\scheduled_runner.py" /F
```

`10:15` is only an example for UTC+10, and the command uses example paths without spaces. Use `11:15` during UTC+11 daylight time, or choose another local time that is safely after the completed UTC candle. For paths containing spaces, use the GUI fields above to avoid `schtasks` quoting ambiguity. Task Scheduler itself does not route stdout to Telegram; use Hermes below when chat delivery is desired.

## Hermes cron example

Hermes no-agent jobs deliver non-empty script stdout verbatim and suppress delivery for empty stdout. Hermes requires cron scripts to live under its profile-local `scripts` directory, so create a credential-free wrapper such as `%LOCALAPPDATA%\hermes\scripts\daily-vwap-advisory.py`:

```python
from pathlib import Path
import subprocess
import sys

project = Path(r"C:\path\to\binance-vwap-scanner")
result = subprocess.run(
    [sys.executable, str(project / "scheduled_runner.py")],
    cwd=project,
    stdout=sys.stdout,
    stderr=sys.stderr,
    check=False,
)
raise SystemExit(result.returncode)
```

After reviewing the wrapper path and converting `00:15 UTC` to the gateway host's local scheduler time, this command is an example of creating the job (it has not been run by this project):

```text
hermes cron create "15 10 * * *" --no-agent --script daily-vwap-advisory.py --deliver telegram --name "Daily VWAP advisory"
```

The `10:15` cron time is only the UTC+10 example. Hermes cron expressions use the gateway host's scheduling clock. Verify without creating or changing a job using:

```text
hermes cron create --help
hermes cron list
```

After an operator intentionally creates the job, use `hermes cron run "Daily VWAP advisory"` for a canary and inspect `hermes cron runs "Daily VWAP advisory" --limit 20`. The default Hermes script timeout is one hour; increase it only if measured scanner refreshes need longer. Telegram credentials remain in Hermes configuration and are never embedded in the runner or wrapper.

## Operational limitations

- The first run emits all alert IDs returned by that refresh because the delivery ledger starts empty; existing historical rows outside the refreshed payload are not backfilled into the digest.
- Deduplication uses atomic claims and acknowledged stdout emission; it does not confirm receipt by an external chat provider. Hermes maintains downstream delivery status separately.
- The probability is an empirical 20-day directional continuation association from the current model, not a trade-success probability.
- Perp-only values use spot-trained probability transfer and are labeled lower confidence.
- The scanner still depends on Binance/Velo availability and the existing `VELO_API_KEY` configuration.
