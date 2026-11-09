# Third-party risk labelling guide

One set of rules for Tom labelling the test set **and** for Haiku (this text becomes its instructions).
When a label and this guide disagree, fix the guide, then relabel. Version 5, 2026-11-08 (themes rules and main theme added).

## What you're reading

The company's **risk chapter**: usually a risk management intro, the list of **principal risks** (sometimes called
key, main or significant risks, or "risks and uncertainties"), and often an **emerging risks** part.
Text comes from the report's electronic version, so tables and diagrams can look jumbled.

## What to record (one row per company)

| Field | Values |
|---|---|
| **Verdict** | yes / passing mention / no / couldn't check |
| **Main theme** | the one theme of the risk and quote behind the verdict (none for no / couldn't check) |
| **Themes** | any of: cyber & security · sanctions, watchlists & PEPs · bribery & corruption · fraud & bad actors · data protection · outsourcing & resilience · human rights & modern slavery (see "Themes" below) |
| **Quote** | the exact words that justify a yes or passing mention (one or two sentences) |
| **Supply chain** | yes / no: supply chain risk appears in the principal risks (not counted; it explains a "no") |
| **TPRM programme** | yes / no: the chapter describes a third-party risk function, framework, committee or due diligence process |
| **Emerging risks** | mentioned / not mentioned / no emerging risks section (same scope as the verdict) |

## What counts as third-party risk

Risk from the **conduct, security or compliance of third parties** the company relies on: suppliers, vendors,
outsourcers, service providers, data processors, agents, intermediaries, distributors.

**In scope**
- Cyber or information security risk **via suppliers or vendors**, including data they hold
- Data protection via processors or vendors
- **Outsourcing and critical vendor or service provider** failure or poor resilience (e.g. a cloud, IT or payments provider)
- Supplier ethics: **human rights, modern slavery, ESG conduct** of suppliers
- **Sanctions, bribery and corruption, fraud, financial crime: only when third parties are involved** (suppliers, agents,
  intermediaries, distributors, partners acting for the company)
- Bad actors among third parties

**Cyber needs a third party.** Cyber attacks in general ("cyber criminals attempting to access our IT systems",
ransomware, phishing of staff) are **not** third-party risk on their own. They count only when the text links them to
suppliers, vendors, outsourcers or partners (Tom, 2026-11-08).

**Out of scope (don't count)**
- **Supply chain**: shortages, non-delivery, logistics disruption, input or commodity prices, "security of supply"
- Contractor and joint venture partner conduct, safety, productivity or availability (e.g. "contractor productivity may be lower than anticipated", a shortage of reliable contractors: Fresnillo), **even when the risk is titled "third-party"** (BP)
- A supplier going bust (supplier financial failure)
- Sanctions or financial crime involving **customers** (e.g. a bank's customer screening, KYC/AML)
- Customer credit risk

## How to decide the verdict

1. **Find the principal risks.** Only risks the company presents as its principal (or key) risks count for the verdict.
   Risk management framework text, governance structure diagrams and climate (TCFD) tables do **not**, unless that's
   where the principal risks are listed. They can still set the **TPRM programme** flag.
2. **Read each principal risk**: its title, description, causes and mitigations.
3. **Yes**: one of the principal risks is **about** in-scope third-party risk: its title names it, or its main description
   is about it. Examples: "Third-party risk", "Outsourcing and supplier management", "Ethical sourcing and human
   rights in our supply chain", "Bribery and corruption" where the description centres on agents or intermediaries.
   Titles can be short ("Third parties") or odd ("External (third-party) process failures"); in this text a risk's
   title sometimes appears **after** its description, because of the page layout.
4. **Passing mention**: inside a **different** principal risk, the text names third parties as a **cause or channel of
   that risk**, or names third-party / supplier risk itself. Examples: "Cyber: … including attacks through our
   suppliers"; "A breach or failure of our third-party supplier's … digital systems" (BP); "Some services depend on
   suppliers' and partners' reliability" (BT); a mitigation that says "to address … third party risks" (Funding
   Circle) or "manages cyber security risks associated with service providers and suppliers" (Tesco). A mention only
   in another risk's mitigations is never a yes.
   **Doesn't count (→ no, but can set TPRM programme = yes):**
   - Generic controls that don't name a third-party risk: a code of conduct for suppliers or "third parties acting on
     our behalf", anti-bribery manuals, supplier audits, screening or due diligence (Chemring, Segro, Severn Trent,
     Fresnillo: Tom, 2026-11-08).
   - "Supplier risk" listed only as a topic that governance or a programme covers ("Board governance … covering risk
     appetite, critical services, supplier risk and metrics": Tate & Lyle).
   - A general compliance duty that includes third parties ("its employees and third parties providing services on
     its behalf comply with all relevant legal and regulatory obligations": Chemring, Tom 2026-11-08). Bribery or
     sanctions count only when the risk describes agents, intermediaries or suppliers as the source of the problem.
   - **Commercial partners**: dependence on alliance, channel or distribution partners for sales, IP or market
     access (Kainos "Partner relationships" with Workday/Microsoft/AWS; MONY "Relevance to partners").
   - The company's **own** mishandling of data it shares with partners or third parties (MONY "Data processing and
     protection"): that's the company's data protection risk, not risk from a processor.
   - "Third parties" meaning outside attackers in general ("third parties … may attempt to use cybercrime
     techniques": Airtel Africa). Attackers aren't suppliers.
   - Supplier human rights / modern slavery as one element of a broader risk, e.g. product safety or reputation
     (Tesco, Mondi: Tom, 2026-11-08). It counts only as its own principal risk (4imprint "Supply chain compliance and
     ethics" → yes).
   **A title isn't enough on its own**: IAG's "Critical third parties in the supply chain" is mostly about aircraft and
   engine deliveries, so Tom labelled it a passing mention (its third-party service-provider content is a minority).
   Judge by what most of the description is about.
5. **No**: no in-scope third-party content in the principal risks. A company whose only relevant risk is supply chain
   is a **no** (with Supply chain = yes).
6. **Couldn't check**: the chapter is missing, cut off, or clearly isn't the principal risks. Don't guess.
7. The highest level wins: one "yes" risk beats several passing mentions.

**Read the description, not just the title.** "Supplier risk" can be either: about deliveries or continuity of goods →
supply chain (out); about vendor security, outsourced services or supplier conduct → third-party (in). A
"Supply chain" risk that also lists supplier ethics or modern slavery → no (see the "doesn't count" list).

**Mixed risks**: when one risk mixes in-scope and out-of-scope third parties (e.g. JV partners **and** suppliers'
compliance), label it as you judge it and **write a note**: those cases tighten this guide.

## Themes

Tag what the **counting third-party text is about**, not everything the surrounding risk covers. Only findings that
count (yes or passing mention) give themes; the main theme comes from the finding behind the verdict and quote.
A theme needs words in the text that name it; don't add one because it's plausible.

| Theme | Tag it when the third-party text names… |
|---|---|
| cyber & security | attacks, breaches or security failures at or through suppliers, vendors or service providers |
| sanctions, watchlists & PEPs | third parties (suppliers, agents, partners, counterparties acting for the company) that are sanctioned, on watchlists, politically exposed or "connected with criminal behaviour"; screening them against such lists |
| bribery & corruption | bribery or corruption by agents, intermediaries, suppliers or partners |
| fraud & bad actors | fraud, misconduct or criminal acts by third parties |
| data protection | personal or customer data held or processed by vendors or processors |
| outsourcing & resilience | reliance on outsourced or critical service providers, or their failure, outage or poor performance |
| human rights & modern slavery | supplier labour practices, human rights, modern slavery or ESG conduct |

**Cyber vs outsourcing**: "a cyber attack on a supplier could expose our data" → cyber & security (+ data protection if
data is named), **not** outsourcing. Add outsourcing & resilience only if the text also talks about relying on the
provider or its service failing ("third-party system outages", "critical suppliers fail to deliver services").

## Examples from the test reports

| Company | What the report says | Label |
|---|---|---|
| Lloyds | Operational risk: key risks include "supplier risk"; "events at third-party suppliers reinforced the need for vigilance and robust oversight" | **Passing mention** · outsourcing & resilience |
| Funding Circle | Operational risk mitigation: "To address external dependencies and third party risks, we perform comprehensive supplier due diligence" | **Passing mention** · outsourcing & resilience · TPRM programme = yes (also a "Supplier Risk Sub-Committee") |
| Tesco | "Security of supply": being "unable to secure the products required to fulfil customer demand" | Supply chain only, so this risk alone → **no** |
| First Tin | "SUPPLY CHAIN ISSUES": "inability to timely acquire strategic consumables, raw materials…" | Supply chain only → **no** |
| Man Group | Principal risk "External (third-party) process failures": "critical third-party service providers do not or are unable to perform services as required" | **Yes** · outsourcing & resilience · TPRM programme = yes (a new function "integrating Operational Risk, Third-Party Risk Management…") |
| Aviva | Principal risk "Third parties": "Aviva relies on a wide range of third parties, and their own suppliers (fourth parties)…" | **Yes** · outsourcing & resilience. (Its generic "cyber criminals" line doesn't count by itself.) |
| Aberdeen | Third party risk: parties "connected with criminal behaviour, or subject to sanctions" … "We rely on third parties to deliver key business activities" | **Yes** · main theme sanctions, watchlists & PEPs (it's named first and is the screening point) · outsourcing & resilience also named |
| BP | "Partner and third-party risk": "performance, standards, or compliance of non-operated joint ventures, strategic partners, contractors, sub-contractors, or other third parties" | **No** (Tom, 2026-11-08): it's about JV partner and contractor conduct, which is out of scope |
