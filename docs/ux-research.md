# UX references and implementation decisions

Reviewed 2026-10-16. These are pattern references; Rowstead keeps its own small
Jinja/JavaScript implementation and does not copy a component library or its assets.

| Primary reference | Relevant behavior | Rowstead decision |
|---|---|---|
| [Cloudscape Wizard](https://cloudscape.design/components/wizard/) | A guided sequence for interrelated configuration tasks | Explicit Upload → Map columns → Review and start; only the current step has the primary action |
| [Cloudscape Create resource](https://cloudscape.design/patterns/resource-management/create/) | Match creation complexity to the task, with clear steps and validation | Keep the three small steps on one route; retain file, preview and mappings when navigating backward |
| [GOV.UK Check answers](https://design-system.service.gov.uk/patterns/check-answers/) | Let people review and change captured information before submission | Show file, row count, source and column mappings before creating/starting a task; use edit links |
| [GOV.UK Validation](https://design-system.service.gov.uk/patterns/validation/) | Explain how to correct an error and preserve entered values | Focus the error summary on failure and retain inputs; distinguish upload/configuration failures from row processing issues |
| [Cloudscape Table view](https://cloudscape.design/patterns/resource-management/view/table-view/) | Search/filter, pagination and distinct empty/no-results/error states | Filter across the full owner's task list on the server; clear filters for zero matches; separate fetch errors from an empty list |

## Prior problems addressed

- A first-time user had to download/re-upload an unexplained sample; a one-click
  successful demo gives a predictable first run. The deliberately failing sample
  is a separate scenario with expected outcomes stated before launch.
- File upload, mapping and immediate execution were grouped together. A review
  step makes the source and mapping consequences visible before processing starts.
- Search previously covered only the current page. Query and exact status filters
  now run before server pagination and return the filtered count.
- “Completed with errors” did not explain whether results were lost. Task copy
  distinguishes saved successful results, not-found records, invalid inputs and
  exhausted retries; a combined issues filter helps inspect the affected rows.
- The default FastAPI documentation depended on blocked CDN/inline resources.
  `/docs` is a local API reference plus downloadable OpenAPI JSON, compatible with
  the panel's content security policy.

## Validation scope

The functional browser checks cover the guided sample path, review/edit,
creation/start failure recovery without duplicate tasks, task filters, issue rows,
mobile layout and sign out. Screenshots are refreshed from the running demo.
These are implementation checks, not a claim of a moderated usability study.
