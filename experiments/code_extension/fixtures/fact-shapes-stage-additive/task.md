Add a triage step for imported jobs.

Jobs created by an import must start in a new triaged stage instead of the initial waiting stage. Jobs created directly keep starting in the initial waiting stage. A job leaves triaged in one of two ways, each with a reason that stays in the job's history: released into the initial waiting stage, or rejected by moving it to the completed stage. No other move into or out of triaged is allowed. Jobs in triaged must never be picked for a build.

Triaged jobs are open work. While a job is in triaged, its priority, owner and evidence can be changed as for any job still in progress. Triaged jobs can be released or rejected in bulk, like single jobs. Triaged jobs can have escalation rules, so imported jobs left untriaged too long are escalated. Exports always show a triaged job's current priority and owner. Reports and digests show triaged jobs under the heading "Awaiting triage". Archived triaged jobs are kept for at most 30 days.

The new stage must work everywhere in the service that the existing stages work, stored data included.

A job id made of letters, digits, underscores or hyphens must be accepted for stage changes up to 80 characters long, and longer or otherwise malformed job ids must be rejected.
