# Project auto-closes when `out_date` is set

When an operator sets `project_t.out_date` (the delivery date), webSAMS automatically flips `project_t.status` to `closed`. Operators do not flip status manually for this transition. This makes the delivery date the single load-bearing signal for closure and prevents the common drift where `out_date` is set but `status` is still `running`.

`prepaid` projects are unaffected — `prepaid` is a billing flag in the status field that does not represent the workflow position (see [ADR-0001](0001-submitter-naming.md) context and the project-status notes in `CONTEXT.md`). Billing fields (`invoice_date`, `invoice_nr`, `price`) are filled independently of `out_date` and do not drive status.
