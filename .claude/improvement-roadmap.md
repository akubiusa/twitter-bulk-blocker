# Improvement ideas

Unscheduled proposals; none of these exist in the code or the monitoring scripts today.

## Monitoring

- Early warning: track cookie expiry, remaining API rate limit and small drops in success rate, and refresh cookies or slow down before errors occur.
- Resource monitoring: CPU and memory per container.
- Detailed performance analysis to find bottlenecks.

## Automation

- Automatic container restart when an error threshold is reached.
- Automatic detection and refresh of expired cookies.
- Automatic stop of containers that have finished processing.
- Dynamic adjustment of the batch size.

## Longer term

- Automated testing and deployment of new releases.
- Automatic escalation and notification.
- Automatic log retention and audit reports.
