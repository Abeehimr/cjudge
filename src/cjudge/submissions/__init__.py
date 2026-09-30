"""Submission evidence and queue metadata; artifacts are never public paths."""
import sqlalchemy as sa

from cjudge.identity import metadata

submissions = sa.Table('submissions', metadata,
    sa.Column('id', sa.Uuid(), primary_key=True),
    sa.Column('lab_id', sa.Uuid(), sa.ForeignKey('labs.id'), nullable=False),
    sa.Column('account_id', sa.Uuid(), sa.ForeignKey('accounts.id'), nullable=False),
    sa.Column('revision_id', sa.Uuid(), sa.ForeignKey('task_revisions.id'), nullable=False),
    sa.Column('idempotency_key', sa.Uuid(), nullable=False),
    sa.Column('filename', sa.String(160), nullable=False),
    sa.Column('sha256', sa.String(64), nullable=False),
    sa.Column('size', sa.Integer(), nullable=False),
    sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('client_ip', sa.String(45), nullable=False),
    sa.Column('client_mac', sa.String(17)), sa.Column('mac_source', sa.String(160)),
    sa.Column('mac_observed_at', sa.DateTime(timezone=True)),
    sa.UniqueConstraint('lab_id', 'account_id', 'idempotency_key'),
    sa.CheckConstraint('size > 0 AND size <= 65536'))
sa.Index('submissions_history', submissions.c.lab_id, submissions.c.account_id, submissions.c.accepted_at)

jobs = sa.Table('judge_jobs', metadata,
    sa.Column('submission_id', sa.Uuid(), sa.ForeignKey('submissions.id'), primary_key=True),
    sa.Column('state', sa.String(16), nullable=False, server_default='queued'),
    sa.Column('attempt_id', sa.Uuid()),
    sa.Column('attempt_count', sa.Integer(), nullable=False, server_default='0'),
    sa.Column('retry_until', sa.Integer(), nullable=False, server_default='3'),
    sa.Column('ready_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.CheckConstraint("state IN ('queued', 'judging', 'delayed', 'complete')"))
sa.Index('jobs_ready', jobs.c.state, jobs.c.ready_at)

turns = sa.Table('judge_turns', metadata,
    sa.Column('account_id', sa.Uuid(), sa.ForeignKey('accounts.id'), primary_key=True),
    sa.Column('claimed_at', sa.DateTime(timezone=True)))

workers = sa.Table('judge_workers', metadata,
    sa.Column('slot', sa.Integer(), primary_key=True),
    sa.Column('generation', sa.Uuid(), nullable=False),
    sa.Column('state', sa.String(16), nullable=False),
    sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('attempt_id', sa.Uuid()),
    sa.Column('completed', sa.Integer(), nullable=False, server_default='0'),
    sa.Column('fault', sa.String(200)))

attempts = sa.Table('judge_attempts', metadata,
    sa.Column('id', sa.Uuid(), primary_key=True),
    sa.Column('submission_id', sa.Uuid(), sa.ForeignKey('submissions.id'), nullable=False),
    sa.Column('worker_slot', sa.Integer(), nullable=False),
    sa.Column('worker_generation', sa.Uuid(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('lease_until', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True)),
    sa.Column('outcome', sa.String(16)), sa.Column('fault', sa.String(200)))

runs = sa.Table('judge_runs', metadata,
    sa.Column('id', sa.Uuid(), sa.ForeignKey('judge_attempts.id'), primary_key=True),
    sa.Column('submission_id', sa.Uuid(), sa.ForeignKey('submissions.id'), nullable=False),
    sa.Column('revision_id', sa.Uuid(), sa.ForeignKey('task_revisions.id'), nullable=False),
    sa.Column('verdict', sa.String(16), nullable=False),
    sa.Column('passed', sa.Integer(), nullable=False), sa.Column('total', sa.Integer(), nullable=False),
    sa.Column('score_numerator', sa.Text(), nullable=False), sa.Column('score_denominator', sa.Text(), nullable=False),
    sa.Column('compiler_feedback', sa.Text(), nullable=False),
    sa.Column('compiler_truncated', sa.Boolean(), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=False))

cases = sa.Table('judge_case_results', metadata,
    sa.Column('run_id', sa.Uuid(), sa.ForeignKey('judge_runs.id'), primary_key=True),
    sa.Column('number', sa.Integer(), primary_key=True), sa.Column('verdict', sa.String(8), nullable=False),
    sa.Column('cpu_seconds', sa.Float(), nullable=False), sa.Column('wall_seconds', sa.Float(), nullable=False),
    sa.Column('memory_kib', sa.Integer(), nullable=False),
    sa.Column('stdout', sa.LargeBinary(), nullable=False), sa.Column('stderr', sa.LargeBinary(), nullable=False),
    sa.Column('stdout_truncated', sa.Boolean(), nullable=False), sa.Column('stderr_truncated', sa.Boolean(), nullable=False))

TABLES = (submissions, jobs, turns, workers, attempts, runs, cases)
