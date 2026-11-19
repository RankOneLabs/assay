Add a triage step for imported jobs.

Jobs created by an import must start in a new triaged stage instead of the initial waiting stage. Jobs created directly keep starting in the initial waiting stage. While a job is in triaged, its priority and owner can be changed as for any open job. It then leaves triaged in one of two ways, each with a reason that stays in the job's history: released into the initial waiting stage, or rejected by moving it to the completed stage. No other move into or out of triaged is allowed.

Jobs in triaged must never be picked for a build.

The new stage must work everywhere in the service that the existing stages work, stored data included.

Labels containing letters, digits, underscores or hyphens must be accepted up to a length of 80 characters, and longer or otherwise malformed labels must be rejected.
