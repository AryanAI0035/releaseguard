# Engineering review notes

An implementation review found that updating a worker lease only between measurement windows was insufficient. With the permitted workload (100 requests, concurrency 1, deadline 2 seconds), a window could take approximately 200 seconds, exceeding the 120-second lease. A second worker could then reclaim an active job.

The correction adds a periodic heartbeat task while measurement runs. Ownership is also verified transactionally when writing results. Interrupted work is assigned a new attempt, and final reports exclude old partial attempts.

The tests verify exclusive claiming, expired-lease recovery, partial-attempt exclusion, and continued ownership during a long window. HTTP requests may repeat after a worker restart; completed reports include only the final attempt.

A second review found that treating every unusual performance window as a regression created too many alerts. The initial experiment is preserved. The correction applies the already specified practical latency-change budget to operational flags, preserves raw results, and evaluates the changed policy on a fresh collection. The evaluation compares both methods using the same alert policy.
