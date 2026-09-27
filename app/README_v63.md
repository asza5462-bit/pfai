# PFAI v6.3 — Global Job Scheduler

Built from the verified PFAI v6.1 tree. Adds policy-aware global scheduling across explicitly authorized workers, with priorities, dependencies, resource matching, checkpoints, worker-failure recovery, and persistent job state in the scheduler object.

Security boundary: the scheduler only considers workers marked `authorized=True` and healthy/ready. It does not discover, scan, commandeer, or use unowned infrastructure.
