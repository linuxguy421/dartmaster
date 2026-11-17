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

The engine should expose one logical match identity and a phase/state indicating whether
the first game is pending, the reset is pending, or the championship is complete. The
source game IDs remain available for routing, diagnostics, and audit history, but the
operator UI must not show `GF` and `GGF` as separate matches.

This is a domain-modeling rule, not permission to rewrite the JSON definitions. Preserve
their exact game order and routing. If a bracket's `GGF` participants or routes are
malformed or inconsistent, report the anomaly and do not silently repair it.

## Board scheduling

A logical match occupies at most one board at a time. A championship match that enters
its reset phase retains its current board assignment. The scheduler must never schedule
the reset as a second concurrent match or allow another match to take that board between
the first game and the reset.
