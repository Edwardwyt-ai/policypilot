"""Build the evaluator-only Need gold set for 67 banking tasks.

The compact specifications below are deliberately semantic.  They describe
what must be known, which source/capability may establish it, and when it is
complete; they do not prescribe a LangGraph node order or a unique trajectory.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).absolute().parents[1]
OUTPUT = ROOT / "data" / "policypilot" / "evaluation" / "need_gold_v1.json"


def need(
    need_id: str,
    description: str,
    sources: str | tuple[str, ...],
    capabilities: str | tuple[str, ...],
    condition: str,
) -> tuple[str, str, tuple[str, ...], tuple[str, ...], str]:
    if isinstance(sources, str):
        sources = (sources,)
    if isinstance(capabilities, str):
        capabilities = (capabilities,)
    return need_id, description, sources, capabilities, condition


U = "user_dialogue"
P = "policy_kb"
T = "transaction_tool"
E = "prior_verified_evidence"


def requirements(description: str, condition: str) -> tuple:
    return need("user_requirements", description, U, "user_clarification", condition)


def identity() -> tuple:
    return need(
        "verified_identity",
        "The authenticated customer identity required before private account access or mutation.",
        (U, T),
        ("identity_collection", "identity_verification"),
        "Required identity fields are supplied by the user and verification succeeds.",
    )


def policy(description: str, condition: str) -> tuple:
    return need("governing_policy", description, P, "policy_search", condition)


def live_state(description: str, condition: str) -> tuple:
    return need("live_account_state", description, T, "account_or_transaction_lookup", condition)


def execution(description: str, condition: str, capability: str = "account_mutation") -> tuple:
    return need("authorized_execution", description, (T, E), capability, condition)


SPECS: dict[str, list[tuple]] = {
    "task_001": [
        requirements("Personal-card purpose and hard constraints: everyday spend, highest cash back, and no annual fee unless no alternative exists; Rho-Bank+ status is also material.", "Card purpose, annual-fee constraint, reward objective, and subscription status are explicit."),
        policy("Comparable personal-card reward rates, annual fees, and subscription-dependent terms.", "Policy evidence covers every viable personal-card candidate and each stated hard constraint."),
        execution("Application inputs for the selected card and the completed application.", "The policy-backed best-fit card is selected and the application succeeds.", "credit_card_application"),
    ],
    "task_002": [
        requirements("Travel spending profile, premium-benefit preferences, income, annual-fee tolerance, and subscription status.", "All decision-driving travel, fee, income, and subscription facts are explicit."),
        policy("Eligibility, travel rewards, benefits, fees, and promotional terms across plausible personal cards.", "Evidence supports a constraint-by-constraint comparison and a single eligible best fit."),
        execution("Application inputs and successful application for the chosen travel card.", "The recommended eligible card is applied for successfully.", "credit_card_application"),
    ],
    "task_003": [
        requirements("Everyday-spend preferences, hard card constraints, income, and Rho-Bank+ status.", "All hard constraints and eligibility facts needed for card choice are explicit."),
        policy("Personal-card fees, rewards, eligibility, and subscription benefits for viable candidates.", "Every hard constraint is supported by policy evidence and one candidate dominates."),
        execution("Application inputs and completed application for the selected card.", "The policy-backed card application succeeds.", "credit_card_application"),
    ],
    "task_005": [
        identity(),
        live_state("Current account balances plus the account profile and support-code state relevant to the requested email change.", "Balances and the authoritative profile/support state have been retrieved."),
        policy("The special-support-code and identity rules that permit or prohibit an email change.", "Policy evidence establishes whether the change is authorized and what prerequisites apply."),
        execution("The requested email change after all policy and verification prerequisites are met.", "The email change succeeds, or a policy-required handoff is completed without claiming success.", "profile_update_or_handoff"),
    ],
    "task_006": [
        requirements("Everyday-card objective, environmental preference, income, fee tolerance, and subscription status.", "All product constraints and eligibility facts are explicit."),
        policy("EcoCard and alternative personal-card rewards, fees, eligibility, and relevant environmental benefits.", "Policy evidence compares EcoCard against all viable alternatives on the user's constraints."),
        execution("Application inputs and successful application for the best-fit card.", "The chosen card is policy-supported and the application succeeds.", "credit_card_application"),
    ],
    "task_007": [
        requirements("Desired promotional value, acceptable reward form, income, and subscription status.", "Promotion objective and all eligibility facts are explicit."),
        policy("Current promotions, eligibility restrictions, reward value, and card fees for viable cards.", "Evidence identifies the best eligible promotion without relying on the mailed offer alone."),
        execution("Application inputs and completed application for the selected promotional card.", "The eligible best-promotion card application succeeds.", "credit_card_application"),
    ],
    "task_010": [
        identity(),
        live_state("The customer's actual referral records, credited bonuses, rejected referrals, and account types.", "Referral history is retrieved and explains each missing bonus with account-specific evidence."),
        policy("Referral qualification, retry, restriction, and bonus rules for the affected card types.", "Policy evidence can classify the observed referral outcomes and determine whether retry is allowed."),
        execution("A retry referral only when the observed state and policy make it valid.", "An eligible retry is submitted successfully, or evidence establishes that no retry should occur.", "referral_submission"),
    ],
    "task_015": [
        requirements("Which referral programs the customer can use and the objective of maximizing valid referral value.", "Relevant card ownership and referral objective are explicit."),
        policy("Referral availability, bonuses, caps, and qualification rules across the customer's cards.", "Evidence identifies each currently usable program and its exact qualification terms."),
        execution("Safe exposure and use of only the eligible referral capability.", "The eligible referral path is made available and invoked with valid parameters.", "user_tool_enablement"),
    ],
    "task_016": [
        identity(),
        live_state("The specific referral status and the referred account's actual qualifying activity.", "Account-specific referral and transaction state is retrieved."),
        policy("Referral bonus timing and transaction qualification requirements.", "Policy evidence explains the missing bonus and the exact remaining requirement."),
        execution("The remaining user-side qualifying transaction when policy and state show it is appropriate.", "The qualifying transaction succeeds or evidence establishes that no transaction should be requested.", "user_transaction"),
    ],
    "task_017": [
        identity(),
        live_state("Silver Rewards Card transactions and the rewards actually posted for each suspicious transaction.", "All candidate transactions and posted reward amounts are retrieved and paired."),
        policy("Silver Rewards Card earning categories, exclusions, and correction rules.", "Each suspected discrepancy is recalculated from policy evidence."),
        execution("Correction of every confirmed reward discrepancy and no mutation of correctly rewarded transactions.", "All and only confirmed discrepancies are corrected successfully.", "reward_correction"),
    ],
    "task_018": [
        identity(),
        live_state("Transactions and posted rewards across every affected personal and business card.", "All relevant card accounts, transactions, and posted rewards are retrieved."),
        policy("Earning rules and exclusions for every affected card product.", "Each transaction is evaluated against the policy for its own card and category."),
        execution("Corrections for all confirmed discrepancies only.", "Every confirmed mismatch is corrected and valid rewards remain unchanged.", "reward_correction"),
    ],
    "task_019": [
        identity(),
        live_state("Gold Rewards and EcoCard transactions with their posted reward amounts.", "Relevant transactions and rewards for both cards are retrieved."),
        policy("Gold Rewards and EcoCard earning categories and exclusions.", "Each suspected discrepancy has a policy-backed expected reward."),
        execution("Corrections for confirmed reward errors only.", "All confirmed errors are corrected without changing correct entries.", "reward_correction"),
    ],
    "task_020": [
        identity(),
        live_state("Business Silver and personal Silver transactions with posted rewards.", "Relevant transactions and reward postings for both accounts are retrieved."),
        policy("The distinct reward rules for Business Silver and personal Silver cards.", "Every transaction is evaluated under the correct product policy."),
        execution("Corrections for all and only confirmed reward errors.", "Confirmed discrepancies are corrected successfully.", "reward_correction"),
    ],
    "task_021": [
        identity(),
        live_state("Business Bronze and EcoCard transactions and posted rewards.", "Relevant account, transaction, and reward state is retrieved."),
        policy("Business Bronze and EcoCard reward rules, including category-specific conditions.", "Expected reward is supported for each questioned transaction."),
        execution("Correction of confirmed reward discrepancies.", "All confirmed mismatches are corrected and valid entries are untouched.", "reward_correction"),
    ],
    "task_022": [
        identity(),
        live_state("All affected card accounts, their transactions, and posted rewards across the audit scope.", "The complete audit population and posted reward data are retrieved."),
        policy("Reward policies for each personal and business card in the audit.", "Every audited transaction is matched to the correct product/category rule."),
        execution("Corrections for every confirmed discrepancy only.", "The complete set of confirmed errors is corrected without false positives.", "reward_correction"),
    ],
    "task_023": [
        identity(),
        live_state("Current Platinum account status and the spending history relevant to fee rebate eligibility.", "Authoritative account and qualifying spend are retrieved for the required period."),
        policy("Platinum annual-fee rebate thresholds, timing, exclusions, and alternative-card eligibility.", "Evidence determines rebate eligibility and supports any recommended alternative."),
        execution("Any selected replacement or additional card application after the fee analysis.", "The chosen policy-consistent application succeeds, or no application occurs when unnecessary.", "credit_card_application"),
    ],
    "task_024": [
        requirements("Business vehicle purchase amount, business use, repayment plan, reward preference, and fee tolerance.", "Purchase and business constraints needed for product choice are explicit."),
        policy("Business-card limits, rewards, fees, eligibility, and purchase suitability.", "Evidence compares viable business cards against the truck-purchase requirements."),
        execution("Application for the single best eligible business card.", "The selected business-card application succeeds.", "credit_card_application"),
    ],
    "task_025": [
        requirements("Enterprise purchase amount, merchant/category, company scale, repayment assumptions, and fee tolerance.", "All material purchase and eligibility constraints are explicit."),
        policy("Business-card limits, category rewards, fees, eligibility, and large-purchase restrictions.", "Evidence supports a single eligible card for the planned purchase."),
        execution("Application for the selected business card.", "The policy-backed business-card application succeeds.", "credit_card_application"),
    ],
    "task_026": [
        identity(),
        live_state("Both Silver card accounts, questioned transactions, posted rewards, and any prior correction state.", "All relevant live data is retrieved before mutation."),
        policy("Business and personal Silver reward rules plus correction authorization.", "Every questioned reward has a policy-backed expected value and correction eligibility."),
        execution("Agent-side correction of all confirmed reward errors.", "All confirmed errors are corrected and no correct reward is changed.", "reward_correction"),
    ],
    "task_027": [
        identity(),
        live_state("Business Silver and personal Silver transactions and reward postings.", "The questioned transaction population and posted values are complete."),
        policy("Applicable earning rules and exclusions for both Silver products.", "Each discrepancy is either confirmed or rejected with policy evidence."),
    ],
    "task_028": [
        identity(),
        live_state("The full set of affected accounts, transactions, and posted rewards in the multi-card complaint.", "All relevant live records are retrieved and associated with the correct account."),
        policy("Reward and correction rules for every affected product.", "Each transaction has a policy-backed expected reward and mutation decision."),
        execution("All authorized reward corrections.", "Every confirmed discrepancy is corrected exactly once.", "reward_correction"),
    ],
    "task_029": [
        identity(),
        live_state("Affected card transactions, reward postings, and any correction history.", "All questioned records and prior mutations are retrieved."),
        policy("Applicable reward calculations and correction constraints.", "Each questioned reward has a supported expected value and eligibility decision."),
        execution("Corrections for confirmed errors only.", "All eligible corrections succeed without duplicate or unsupported mutation.", "reward_correction"),
    ],
    "task_031": [
        identity(),
        live_state("The exact hotel transaction, amount, date, card, and current dispute status.", "The matching posted transaction and any existing dispute are identified."),
        policy("Card dispute eligibility, evidence, reason classification, deadlines, and provisional-credit rules.", "Evidence determines whether and how the hotel service dispute may proceed."),
        execution("A correctly classified dispute when eligible.", "The dispute is submitted once with the authoritative transaction identifiers and reason.", "transaction_dispute"),
    ],
    "task_033": [
        live_state("The card balance, payment record, source-account debit, posting state, and timing.", "Both sides of the payment are retrieved and reconciled."),
        policy("Payment posting timelines, missing-payment investigation, and escalation rules.", "Policy evidence classifies the delay and identifies the permitted next action."),
        execution("The allowed investigation or human handoff without falsely claiming the balance is fixed.", "The supported resolution path is completed and the observed status is communicated accurately.", "payment_investigation_or_handoff"),
    ],
    "task_036": [
        identity(),
        live_state("Recent card transactions sufficient to identify any suspicious charge.", "The requested transaction window is retrieved with stable transaction identifiers."),
        policy("The rule for distinguishing information review from a disputable unauthorized transaction.", "Any suspicious item has a supported classification and next-step requirement."),
    ],
    "task_037": [
        identity(),
        live_state("Recent transactions and the exact suspicious transaction selected by the user.", "The suspicious transaction is identified from authoritative account history."),
        policy("Dispute eligibility, reason, deadline, and card-compromise handling.", "Policy evidence supports the dispute path and any replacement requirement."),
        execution("User-side dispute submission for the confirmed suspicious charge.", "The correct transaction is disputed once with valid reason data.", "user_transaction_dispute"),
    ],
    "task_038": [
        identity(),
        live_state("All three Amazon transactions, their identifiers, statuses, and the affected card state.", "Each named charge is matched to one authoritative transaction and the card is identified."),
        policy("Dispute classification for each charge plus fraud-driven cancellation and replacement rules.", "Each charge has an eligible reason and the compromised-card response is supported."),
        execution("Three valid disputes and cancellation/reissue of the compromised card.", "Each eligible dispute is submitted once and replacement completes for the correct card.", "dispute_and_card_replacement"),
    ],
    "task_040": [
        identity(),
        live_state("All questioned transactions across the personal and business cards, including account ownership and current dispute state.", "Every requested charge is uniquely matched to its correct card account."),
        policy("Reason-specific dispute eligibility, deadlines, and provisional-credit rules.", "Each transaction has a policy-supported dispute decision and reason."),
        execution("All and only eligible disputes across both cards.", "Every eligible dispute succeeds once with correct transaction/account parameters.", "transaction_dispute"),
    ],
    "task_043": [
        identity(),
        live_state("Platinum account balance, pending items, recurring obligations, and closure readiness.", "All live blockers to closure are retrieved."),
        policy("Card closure prerequisites, balance settlement, fee implications, and replacement-card handling.", "Policy evidence establishes the exact safe closure sequence."),
        execution("Payoff and closure only after prerequisites are satisfied.", "The account reaches a closable state and closure succeeds without unsupported claims.", "credit_card_closure"),
    ],
    "task_044": [
        identity(),
        live_state("Current Gold account usage, balance, benefits, and closure constraints.", "Authoritative account state needed for retention or closure is retrieved."),
        policy("Rho-Bank alternatives, comparative benefits, fees, closure rules, and application eligibility.", "Evidence supports either retention or one eligible replacement without accepting competitor claims as bank policy."),
        execution("The selected retention/closure/application outcome.", "Only the policy-supported account mutation or application succeeds.", "card_retention_or_replacement"),
    ],
    "task_045": [
        identity(),
        live_state("Business Silver account balance, use, pending items, and closure readiness.", "All authoritative closure blockers and relevant usage are retrieved."),
        policy("Business-card closure prerequisites and available Rho-Bank alternatives.", "Policy evidence supports the final keep/close decision and required sequence."),
        execution("Closure only when all prerequisites are satisfied.", "The correct business card is closed or a required blocker is accurately reported.", "credit_card_closure"),
    ],
    "task_047": [
        identity(),
        live_state("Current business-card accounts, balances, eligibility, and closure constraints.", "The affected account and every closure/application prerequisite are retrieved."),
        policy("Closure rules and the rewards, fees, eligibility, and travel fit of Rho-Bank business alternatives.", "Evidence supports a single valid replacement strategy before closure."),
        execution("The approved application and account closure sequence.", "The replacement application and any closure occur in a policy-safe order.", "card_replacement_strategy"),
    ],
    "task_048": [
        identity(),
        live_state("All four card accounts, balances, pending activity, linked payments, and individual closure blockers.", "Closure readiness is known independently for every card."),
        policy("Closure prerequisites and any product-specific retention or replacement constraints.", "Each card has a supported close, defer, or replace decision."),
        execution("Closure of every currently eligible card without forcing blocked closures.", "All eligible cards close successfully and each blocked card remains unchanged with its blocker recorded.", "bulk_credit_card_closure"),
    ],
    "task_050": [
        identity(),
        live_state("Gold account limit, balance, payment history, account age, and recent limit changes.", "All policy inputs for a limit decision are retrieved."),
        policy("Credit-limit increase eligibility, timing, utilization, and approval rules.", "The live account state is evaluated against every applicable eligibility rule."),
        execution("A limit-increase request only when eligible.", "The eligible increase succeeds, or the precise blocking rule is established without mutation.", "credit_limit_change"),
    ],
    "task_051": [
        identity(),
        live_state("Bronze account balance, utilization, limit, age, payment history, and prior increase history.", "All authoritative eligibility inputs are retrieved, including the stated balance."),
        policy("Credit-limit increase rules, especially utilization and outstanding-balance constraints.", "Every eligibility condition is resolved from policy and live state."),
        execution("A limit change only if all conditions pass.", "The increase succeeds when eligible; otherwise no mutation occurs and the blocker is explicit.", "credit_limit_change"),
    ],
    "task_053": [
        identity(),
        live_state("The laptop transaction and dispute status plus the card's complete limit-increase eligibility state.", "The transaction and all account attributes required by both requested operations are retrieved."),
        policy("Non-delivery dispute rules and credit-limit increase rules.", "Both requests have independent policy-backed eligibility decisions."),
        execution("The eligible dispute and any eligible limit increase.", "Each operation executes only if its own prerequisites pass.", "dispute_and_limit_change"),
    ],
    "task_054": [
        identity(),
        live_state("The fraudulent CloudSync transaction, card compromise status, replacement state, and limit-increase eligibility inputs.", "The fraud item and all account attributes for replacement and limit review are retrieved."),
        policy("Unauthorized-charge dispute, compromised-card replacement, and limit-increase rules.", "Each requested operation has an independent supported decision and ordering."),
        execution("Fraud dispute, safe card replacement, and only an eligible limit increase.", "All supported operations complete once in a safe order; unsupported ones do not run.", "fraud_recovery_and_limit_change"),
    ],
    "task_055": [
        identity(),
        requirements("One travel checking recommendation, one emergency-fund savings recommendation, and the $1,500 funding requirement.", "Travel usage, savings objective, and funding amount/method are explicit."),
        policy("Checking travel costs/benefits, savings yield/fees, opening eligibility, and check-deposit rules.", "Evidence supports exactly one eligible checking and one savings choice plus valid funding."),
        execution("Open both selected accounts and deposit the check into the new savings account.", "Both openings and the $1,500 deposit succeed in the required order.", "account_opening_and_funding"),
    ],
    "task_056": [
        identity(),
        requirements("A better business checking account than Navy Blue, a first business savings account, and transfer funding constraints.", "Business needs, comparison baseline, and funding source/amount are explicit."),
        policy("Business checking/savings eligibility, fees, benefits, yield, and transfer rules.", "Evidence supports one better checking and one eligible savings product plus valid funding."),
        execution("Open the selected accounts and fund savings from Navy Blue.", "Openings and the authorized transfer complete successfully.", "business_account_opening_and_funding"),
    ],
    "task_057": [
        identity(),
        requirements("Personal checking constraints, savings objective, and $2,000 check-deposit requirement.", "All product constraints and the funding target are explicit."),
        policy("Checking and savings product fit, opening eligibility, and check-deposit rules.", "Evidence supports one eligible checking choice, one savings choice, and valid funding."),
        execution("Open the selected accounts and deposit the check into checking.", "Both accounts open and the $2,000 checking deposit succeeds.", "account_opening_and_funding"),
    ],
    "task_058": [
        identity(),
        requirements("The $20,000 one-year holding plan and objective to maximize net return across a new card and savings account.", "Amount, horizon, transaction assumptions, and eligibility preferences are explicit."),
        policy("Card rewards/fees, savings APY/tiers/boosts/fees, cross-product benefits, and opening rules.", "A net-return calculation covers all viable bundles and every material condition."),
        execution("Apply for the selected card, open savings, and deposit $20,000.", "The policy-backed bundle is opened and funded successfully.", "product_bundle_opening"),
    ],
    "task_059": [
        identity(),
        requirements("The $5,000 one-year holding plan and objective to maximize net annual return from a card/savings bundle.", "Amount, horizon, and all eligibility/preferences are explicit."),
        policy("Card rewards/fees and savings rates, tiers, boosts, fees, and opening constraints.", "Net-return evidence compares every viable bundle at the stated balance."),
        execution("Apply for the chosen card, open savings, and fund it with $5,000.", "The selected bundle opens and funding succeeds.", "product_bundle_opening"),
    ],
    "task_060": [
        identity(),
        requirements("Close the empty Green checking account and choose one emergency-fund savings product under the user's constraints.", "Closure intent and all savings constraints are explicit."),
        live_state("Green checking balance and closure blockers plus existing relationships relevant to savings eligibility.", "The old account is confirmed closable and relevant existing products are known."),
        policy("Checking closure rules and savings rates, fees, eligibility, and benefits.", "Evidence supports the closure and exactly one eligible savings recommendation."),
        execution("Close Green checking and open the selected savings account.", "Both operations complete in a safe supported order.", "account_reorganization"),
    ],
    "task_062": [
        identity(),
        requirements("Which existing accounts to retain/close, the new LLC's business-checking needs, and the savings-upgrade objective.", "All reorganization goals and business constraints are explicit."),
        live_state("All existing account balances, ownership, age, and closure/opening blockers.", "Authoritative state is complete for every account affected by the reorganization."),
        policy("Closure rules plus business-checking and savings product eligibility/fit.", "Evidence supports one coherent target account configuration."),
        execution("Close eligible unwanted accounts and open the selected business checking and savings products.", "The supported target configuration is reached without invalid closures.", "account_reorganization"),
    ],
    "task_063": [
        identity(),
        requirements("The $8,000 one-year savings objective and willingness to add a card only when it improves total return.", "Balance, horizon, withdrawal assumptions, and card constraints are explicit."),
        policy("Savings rates/tiers/boosts and card rewards/fees/eligibility across viable bundles.", "A comparable annual-return calculation resolves every bundle condition."),
        execution("Open and fund the best savings option and apply for a card only when justified.", "The highest supported return configuration is opened and funded.", "product_bundle_opening"),
    ],
    "task_064": [
        identity(),
        requirements("The $30,000 one-year plan, active Rho-Bank+ status, and objective to maximize total return across card and savings products.", "Balance, horizon, subscription, and card preferences are explicit."),
        policy("Subscription-sensitive savings boosts, balance tiers, card rewards/fees, and bundle eligibility.", "Net-return evidence covers every viable subscription-aware bundle."),
        execution("Open, apply, and fund the selected bundle.", "The best supported bundle is established and $30,000 is deposited.", "product_bundle_opening"),
    ],
    "task_065": [
        identity(),
        requirements("Maximize one-year interest on $6,000, replace Light Blue with a better checking account, close Light Blue, and do not add a credit card.", "All savings, checking, closure, and no-card constraints are explicit."),
        live_state("Light Blue balance and closure readiness plus existing relationships affecting eligibility.", "The old account is confirmed closable and all relevant relationships are retrieved."),
        policy("Savings yield/fees, checking benefits/fees, eligibility, and closure rules without card-dependent options.", "Evidence supports one savings and one checking choice while honoring the no-card constraint."),
        execution("Open the selected accounts, deposit $6,000, and close Light Blue.", "The target account configuration and funding complete without a card application.", "account_reorganization"),
    ],
    "task_066": [
        identity(),
        requirements("Maximize one-year return on $6,000, upgrade checking, close Light Blue, and allow a card only if it improves return.", "All balance, horizon, checking, closure, and optional-card constraints are explicit."),
        live_state("Light Blue closure readiness and existing product relationships.", "All live prerequisites and current relationships are retrieved."),
        policy("Savings tiers/boosts, checking benefits, card-dependent boosts/fees, and closure rules.", "Comparable net-return evidence determines whether a card is beneficial."),
        execution("Establish the optimal account bundle, fund savings, and close Light Blue safely.", "All supported operations complete and any card is added only when net-beneficial.", "account_reorganization"),
    ],
    "task_067": [
        identity(),
        requirements("Maximize one-year return on $100,000 while upgrading checking, closing Light Blue, and considering a return-improving card.", "High-balance amount, horizon, and all bundle constraints are explicit."),
        live_state("Existing Light Blue state and relationships relevant to high-balance product eligibility.", "Closure readiness and current relationship benefits are retrieved."),
        policy("High-balance savings tiers/caps, checking benefits, card boosts/fees, and closure rules.", "Net-return evidence accounts for balance caps and all bundle costs."),
        execution("Open/fund the optimal products and close Light Blue in a safe order.", "The supported high-balance configuration is reached successfully.", "account_reorganization"),
    ],
    "task_068": [
        identity(),
        requirements("Maximize one-year return on $25,000, upgrade checking, close Light Blue, and optionally add a beneficial card.", "Amount, horizon, and all account/card constraints are explicit."),
        live_state("Current Light Blue state and existing relationships.", "Closure readiness and relevant relationship facts are authoritative."),
        policy("Savings tiers/boosts, checking benefits, card costs/boosts, and closure requirements.", "A net-return comparison supports one complete target configuration."),
        execution("Open and fund selected products and safely close Light Blue.", "The target bundle is established with $25,000 funded.", "account_reorganization"),
    ],
    "task_069": [
        identity(),
        requirements("Maximize one-year return on $10,000, replace Light Blue checking, close it, and consider a card only when beneficial.", "Amount, horizon, and bundle constraints are explicit."),
        live_state("Light Blue balance, closure readiness, and existing relationship state.", "All live blockers and relationship facts are retrieved."),
        policy("Savings rates/tiers, checking benefits, card-linked boosts/costs, and closure rules.", "Evidence supports a single net-optimal configuration."),
        execution("Open/fund selected products and close Light Blue safely.", "The supported configuration is completed and funded with $10,000.", "account_reorganization"),
    ],
    "task_070": [
        identity(),
        requirements("One business checking account satisfying ease-of-use, perks, overdraft-fee, and other stated business constraints.", "Business profile and every hard/soft checking requirement are explicit."),
        policy("Business-checking fees, overdraft treatment, operational features, perks, and eligibility.", "Evidence covers all viable products and supports exactly one best fit."),
        execution("Open the single selected business checking account.", "The recommended eligible account opens successfully.", "business_account_opening"),
    ],
    "task_071": [
        identity(),
        requirements("One business checking and one business savings account satisfying all studio, fee, feature, and yield constraints.", "Every checking/savings hard constraint and business fact is explicit."),
        policy("Business checking and savings fees, features, rates, tiers, eligibility, and relationship benefits.", "Evidence supports exactly one compatible checking/savings pair."),
        execution("Open both selected business accounts.", "Both recommended eligible accounts open successfully.", "business_account_opening"),
    ],
    "task_072": [
        identity(),
        live_state("November ATM transactions and assessed fees for both Bluest and Light Green accounts.", "Every questioned ATM fee is retrieved with account, network, location, currency, and amount."),
        policy("ATM fee and reimbursement rules for both checking products.", "Each assessed fee has a policy-backed expected amount and reimbursement decision."),
        execution("Correction or reimbursement of confirmed ATM-fee errors only.", "All confirmed errors are corrected and valid fees remain unchanged.", "fee_correction"),
    ],
    "task_073": [
        identity(),
        live_state("November ATM transactions and fees across Blue, Green, and Light Green accounts.", "All questioned fees are associated with their correct account and ATM context."),
        policy("Account-specific ATM fee and reimbursement rules.", "Each fee is evaluated under the correct product policy."),
        execution("Correction of every confirmed fee error only.", "Confirmed errors are corrected without changing valid fees.", "fee_correction"),
    ],
    "task_074": [
        identity(),
        live_state("November ATM transactions and fees across all four checking accounts.", "The complete questioned fee set and transaction context are retrieved."),
        policy("ATM fee, foreign-use, network, and reimbursement rules for each account product.", "Every fee has a policy-backed expected treatment."),
        execution("All eligible ATM-fee corrections.", "Every confirmed discrepancy is corrected exactly once.", "fee_correction"),
    ],
    "task_075": [
        identity(),
        requirements("A new checking account minimizing foreign, out-of-network ATM cost during a three-month Southeast Asia trip.", "Trip duration, geography, ATM pattern, currency use, and other constraints are explicit."),
        policy("ATM fees, foreign transaction/conversion costs, reimbursements, caps, account fees, and eligibility for all viable checking products.", "A comparable trip-cost estimate supports one lowest-cost eligible account."),
        execution("Open the selected travel checking account.", "The policy-backed lowest-cost account opens successfully.", "account_opening"),
    ],
    "task_076": [
        identity(),
        requirements("A European-travel checking account minimizing ATM costs while also providing required early direct deposit.", "Travel/ATM assumptions and early-deposit hard constraint are explicit."),
        policy("Foreign and out-of-network ATM costs, reimbursements, early direct-deposit availability, fees, and eligibility.", "Evidence proves one eligible account satisfies early deposit and minimizes expected trip cost."),
        execution("Open the selected checking account.", "The eligible best-fit travel account opens successfully.", "account_opening"),
    ],
    "task_077": [
        identity(),
        live_state("Both checking accounts, their debit cards, current status, and any pending replacement orders.", "Each missing card is uniquely identified and duplicate replacement risk is resolved."),
        policy("Lost-card freeze/closure, replacement, delivery, and account-specific fee rules.", "The required handling for each card is established from policy."),
        execution("Freeze/close and replace both missing debit cards exactly once.", "Both correct cards are secured and replacement orders succeed without duplicates.", "debit_card_replacement"),
    ],
    "task_078": [
        identity(),
        live_state("All three checking accounts, linked debit cards, statuses, and pending replacements.", "Every lost card is mapped to the correct account and current order state."),
        policy("Lost-card security and replacement rules for each account/card.", "Policy evidence supports the required action for all three cards."),
        execution("Secure and replace all three lost debit cards.", "Each affected card is handled exactly once and all replacement orders succeed.", "debit_card_replacement"),
    ],
    "task_079": [
        identity(),
        live_state("All stolen debit cards, linked accounts, card status, and pending replacement state.", "Every stolen card is authoritatively identified with no duplicate-order ambiguity."),
        policy("Stolen-card freeze/closure, fraud precaution, replacement, and delivery rules.", "The required security sequence is supported for each card."),
        execution("Immediately secure and replace all stolen debit cards.", "All affected cards are disabled and replacement orders complete exactly once.", "debit_card_replacement"),
    ],
    "task_080": [
        identity(),
        live_state("Three debit cards and two credit cards in the stolen wallet, including statuses and pending replacement orders.", "All five cards are mapped to authoritative accounts and current replacement state."),
        policy("Debit- and credit-card stolen-card handling, replacement, delivery, and fee rules.", "A supported security/replacement plan exists for each of the five cards."),
        execution("Secure and replace all five cards exactly once.", "Every affected card is disabled and replacement completes without omissions or duplicates.", "multi_card_replacement"),
    ],
    "task_090": [
        identity(),
        live_state("All three debit cards, PIN failure/lock state, recent attempts, and account/card status.", "Each decline is tied to authoritative PIN/card state."),
        policy("PIN retry, lockout, reset, security, and escalation rules.", "The permitted recovery path is known independently for each card."),
        execution("Recover each eligible PIN-locked card or hand off only where policy requires it.", "All cards reach the correct resolved or escalated state without unsafe resets.", "pin_recovery"),
    ],
    "task_093": [
        identity(),
        live_state("Silver savings balances, interest postings, qualification history, and linked-account state for the relevant periods.", "All values required to recompute expected interest are retrieved."),
        policy("Silver savings base rate, tiers, boosts, qualification windows, and posting calculation.", "Expected interest is reproducibly calculated for each questioned period."),
        execution("Correction of any confirmed interest underpayment only.", "A confirmed discrepancy is corrected, or exact evidence shows the posting is correct.", "interest_correction"),
    ],
    "task_098": [
        identity(),
        requirements("The friend's actual customer relationship/location facts and the objective of maximizing valid combined referral value for a personal checking account.", "Referral-recipient facts and product constraints are explicit without relying on casual labels like roommate."),
        live_state("Referrer's current referral history, caps, and eligibility state.", "Authoritative referral usage and remaining capacity are retrieved."),
        policy("Personal checking referral bonuses, recipient eligibility, product eligibility, stacking, geography, and caps.", "Evidence supports one valid highest-value referral choice."),
        execution("Submit the single eligible best-value referral.", "The referral succeeds with the policy-supported account type.", "referral_submission"),
    ],
    "task_099": [
        identity(),
        requirements("The new LLC's actual ownership, business needs, and objective of maximizing the referrer's valid business-checking bonus.", "Recipient business facts and hard product constraints are explicit."),
        live_state("The referrer's current referral history, limits, and eligibility.", "Referral capacity and any prior conflicting referrals are retrieved."),
        policy("Business-checking referral bonuses, product/recipient eligibility, caps, and qualification rules.", "Evidence identifies one highest-value eligible referral product."),
        execution("Submit the selected business-checking referral.", "The valid highest-value referral succeeds once.", "referral_submission"),
    ],
    "task_101": [
        identity(),
        requirements("The true relationship and needs of each of four prospective referrals, separated into personal and business recipients.", "Each recipient's legal/business status and relevant product constraints are explicit."),
        live_state("Year-to-date referral history, product-specific caps, and remaining eligibility.", "Authoritative remaining referral capacity is known before selecting recipients."),
        policy("Personal/business checking referral eligibility, bonuses, caps, recipient restrictions, and stacking rules.", "Each candidate has an independent eligibility/value decision and the optimal feasible subset is known."),
        execution("Submit only the optimal eligible referrals within all caps.", "Every selected referral succeeds once and no ineligible or cap-exceeding referral is submitted.", "referral_submission"),
    ],
}


def build_task_gold(items: list[tuple]) -> dict:
    return {
        "expected_needs": [
            {"id": item[0], "description": item[1]} for item in items
        ],
        "allowed_acquisition": [
            {
                "need_id": item[0],
                "sources": list(item[2]),
                "capabilities": list(item[3]),
            }
            for item in items
        ],
        "completion_condition": [
            {"need_id": item[0], "condition": item[4]} for item in items
        ],
    }


def main() -> None:
    if len(SPECS) != 67:
        raise ValueError(f"expected 67 task specifications, got {len(SPECS)}")
    payload = {
        "schema_version": "need-gold-v1",
        "domain": "banking_knowledge",
        "source_task_count": 97,
        "selected_task_count": len(SPECS),
        "selection_method": (
            "Stratified coverage of product selection, rewards, disputes, account "
            "maintenance, account opening/closure, fees, card replacement, PIN "
            "recovery, interest, and referrals; near-duplicate and handoff-only "
            "tasks were down-sampled."
        ),
        "tasks": {task_id: build_task_gold(items) for task_id, items in SPECS.items()},
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    main()
