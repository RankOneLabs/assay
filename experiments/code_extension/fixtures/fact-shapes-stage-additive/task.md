Add review to the jobs of a run.

When a build of a job that belongs to a run succeeds, the job waits in a new in_review stage until a reviewer approves it, which completes it, or sends it back to active with a reason that stays in the job's history. A reviewer can also re-queue a completed job, which puts it back in the queue for another attempt, even if its run has finished. Approving, sending back and re-queuing are ordinary stage changes, made singly or in bulk.

Runs and jobs must always reflect what they contain: their status, counts and times match their jobs and attempts after every move, single or in bulk, including for data already stored. Add roll-up behavior through the existing roll-up declarations, so a later field or level gets it without new update code.

A job id made of letters, digits, underscores or hyphens must be accepted for stage changes up to 80 characters long, and longer or otherwise malformed job ids must be rejected.
