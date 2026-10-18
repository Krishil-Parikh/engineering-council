# Project: Aegis Freight – Multi-Tenant Real-Time Logistics Orchestration Platform

## Problem
Mid-size freight forwarders coordinate shipments across ocean, air, rail and road using email, spreadsheets and a dozen carrier portals. Delays, customs holds and port congestion are discovered hours late, rerouting is manual, and no one can say what a disruption will cost until after it has happened.

Build a multi-tenant platform that ingests live shipment signals, predicts disruptions, proposes and (with approval) executes reroutes, and keeps a tamper-evident audit trail.

## Core capabilities
1. **Ingestion**: carrier APIs, EDI (214/310/315), AIS vessel positions, flight status feeds, IoT container sensors (temperature, shock, door-open), and forwarded customer emails. Sources are unreliable, duplicated, out of order, and sometimes contradictory.
2. **Shipment digital twin**: a single event-sourced timeline per shipment that reconciles conflicting sources, with confidence scores and a way to replay history as of any past time.
3. **Disruption prediction**: ETA and delay-risk models per leg using weather, port congestion, customs history and carrier reliability. Predictions must be explainable to an operator.
4. **Reroute optimizer**: given a disrupted shipment, generate ranked alternatives (mode, carrier, port) under cost, deadline, hazmat/cold-chain, customs and carbon constraints, with a what-if simulator.
5. **Human-in-the-loop execution**: approval workflows with tenant-defined policies (for example, auto-approve under USD 2,000 extra cost), booking through carrier APIs, rollback when a booking partly fails.
6. **Customer portal**: live tracking, proactive notifications (email, SMS, WhatsApp, webhook), and SLA breach credits calculated automatically.
7. **Compliance**: sanctions screening of parties and vessels, dangerous goods rules, customs document generation, data residency per tenant (EU, US, India).
8. **Audit**: append-only, hash-chained audit log of every decision, human or automated, exportable for regulators.

## Scale and quality targets
- 500 tenants, 2 million active shipments, peak 20,000 events per second.
- Event-to-operator-dashboard latency under 3 seconds at p95.
- 99.95% availability for tracking and alerting; booking may degrade gracefully.
- Strict tenant isolation: no cross-tenant data leakage, including in ML features and caches.
- Every automated action must be reversible or explicitly flagged as irreversible.

## Constraints
- Small team (8 engineers), 9 months to first paying customers.
- Must run on a single cloud first, but avoid designs that make a second cloud or on-prem impossible.
- Customers include GDPR-regulated EU firms, so personal data handling and deletion requests matter.
- Carrier APIs are slow, rate limited and frequently down.

## Open questions the council should settle
- Event sourcing everywhere, or only for the shipment twin?
- Build the prediction models in-house or start with rules plus a vendor?
- Shared database with row-level isolation, or per-tenant schemas, or per-tenant databases?
- How much automation is safe in the MVP, and what is deferred?
- How are conflicting source facts resolved, and who can override them?
