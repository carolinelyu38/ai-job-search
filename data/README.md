# data/

Tracked state for the scheduled watchers.

`amazon_watch_state.json` holds the amazon.jobs `job_path` values that
`tools/amazon_watch.py` has already reported. It is committed on purpose: the
scheduled Routine runs in a fresh container each morning, so an ignored state
file would reset every day and the same Early Career postings would be
re-reported forever. The file contains public posting paths only, no personal
data.
