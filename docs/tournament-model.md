# Tournament match model

## Championship final and conditional reset

The bracket JSON files may define the championship final as two game nodes, conventionally
`GF` and `GGF`. Those nodes are implementation details of the bracket topology; they
must not become two independently scheduled tournament matches.

Dartmaster presents and manages them as one logical **Championship Match**:

1. The championship match is assigned to one board and remains assigned there through
   any conditional reset.
2. The first game uses the bracket's `GF` definition and its existing participant and
   routing references.
3. If the upper-bracket finalist wins, the championship is complete. The reset is skipped.
4. If the lower-bracket finalist wins, both finalists have one loss, so the conditional
   reset is activated. The same two teams play the reset on the same board, without
   releasing the board or creating a second queue entry.
5. The reset uses the source bracket's `GGF` definition for its winner/loser outcomes.
   When it completes, the championship match is complete.

The bracket runtime exposes one logical match identity (`CHAMPIONSHIP`) and a phase
indicating whether the first game is pending, the reset is pending, or the championship
is complete. The source game IDs remain available for routing, diagnostics, and audit
history, but the operator UI must not show `GF` and `GGF` as separate matches.

The initial progression engine is implemented in `app/brackets/runtime.py`. It resolves
`Tn`, `W-Gn`, and `L-Gn` references, returns ready matches in JSON insertion order,
validates winner submissions, and records terminal placements. Calling
`record_winner("CHAMPIONSHIP", team)` records either phase; callers never submit
`GGF` as a separate match. If the source reset references cannot resolve, the runtime
raises a bracket error rather than silently substituting participants.

This is a domain-modeling rule, not permission to rewrite the JSON definitions. Preserve
their exact game order and routing. If a bracket's `GGF` participants or routes are
malformed or inconsistent, report the anomaly and do not silently repair it.

## Board scheduling

A logical match occupies at most one board at a time. A championship match that enters
its reset phase retains its current board assignment. The scheduler must never schedule
the reset as a second concurrent match or allow another match to take that board between
the first game and the reset.

The scheduler supports two operating modes:

- **Manual (default):** no boards are enabled initially. The operator explicitly enables
  the boards that will be in service. Ready matches are then assigned to those enabled
  boards in JSON-defined priority order; unused boards remain idle.
- **Auto:** all configured boards are eligible, and the scheduler fills idle boards
  with the earliest eligible matches. It never schedules a match before both teams
  resolve, and it does not exceed the configured board count.

Changing from auto to manual returns control of board selection to the operator; the
operator must enable the desired boards. An active board cannot be disabled until its
match is complete. Mode affects board availability only, not bracket order or match
eligibility.

The implementation is in `app/brackets/scheduler.py`. It is independent of the web
interface and persistence layer. A malformed conditional reset leaves the championship
assignment reserved on its original board with a visible blocking reason rather than
freeing the board or silently changing the bracket participants.

## Durable tournament state

The first persistence layer uses SQLite and stores a versioned tournament snapshot plus
an append-only operator event history. The snapshot contains the selected bracket file,
seed-to-team assignments, ordered match results, placements, championship phase,
champion, scheduler mode, operator-enabled boards, and current board assignments.

Match results are replayed through the bracket runtime when a tournament is restored.
The stored loser, placements, championship phase, and champion are checked against the
replayed bracket state; the snapshot is rejected if those values disagree. Board
assignments are also checked against the restored runtime before they are accepted.
The source bracket JSON remains external and authoritative; it is loaded by the caller
and is never copied into or rewritten by the state store.

`TournamentStateStore` provides transactional snapshot writes and event appends.
`TournamentSession` coordinates operator actions with persistence: creating a
tournament, enabling/disabling boards, changing scheduler mode, assigning ready matches,
and recording a match winner. A match completion and the resulting board reallocation
are saved together as one state update. The default scheduler mode remains manual.

The state schema is versioned. Future schema changes must use explicit migrations;
do not silently reinterpret or discard an existing tournament snapshot.

## Player and team registration

Registration is represented independently of the web layer in `app/registration/`.
Each player has a stable player ID, display name, and a registered gender value
(`male` or `female`). A team contains exactly two distinct registered players;
same-gender and mixed-gender teams are both valid. A player may belong to only one
team in a tournament. Team names are unique without regard to case.

Registered gender is retained as player information, but this version does not assign
playing order, conduct a coin flip, or model first/second-player roles. The tournament
rule that biological females play first can be applied when turn-order support is
introduced; it does not affect registration, team eligibility, bracket seeding, or
match scheduling in this version.

`TournamentRoster` owns the player pool, team definitions, and explicit seed-to-team
assignments. A team can occupy only one seed, and a seed can have only one team. Before
a tournament starts, the roster must contain exactly the seed assignments referenced
by the selected bracket JSON; missing or unexpected seeds are rejected. The JSON
bracket remains authoritative for game order and progression.

The roster serializes to the tournament's SQLite snapshot alongside match and board
state. Restore reconstructs players and teams through the same validation methods,
then checks that seed assignments produce the exact team names used by the bracket
runtime. A persisted roster that conflicts with the runtime entrants is rejected.

The initial domain API is `register_player(...)`, `create_team(...)`,
`assign_seed(...)`, `validate_for_bracket(...)`, and `runtime_entrants(...)`.
It is intentionally independent of FastAPI so the same validation applies to future API,
admin, and test entrypoints.
