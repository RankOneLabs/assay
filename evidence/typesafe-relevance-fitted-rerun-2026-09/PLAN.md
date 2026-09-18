# Typesafe relevance fitted rerun

Status: exploratory retrospective; **not an adoption gate**.

This report asks the counterfactual question raised after Scout PR #40 merged: how
would the retained Typesafe answers perform if its train-only L2 logistic fitting
machinery had existed before the adoption cohort began? It reuses all 237 structured
answer vectors from the 79-case primary run. It makes no provider calls and does not
change the merged primary report.

The 79 cases have no pre-existing frozen train/held-out partition. To avoid scoring
rows used to fit their own model, this replay uses five-fold stratified
cross-validation with `shuffle=True` and `random_state=0`. All three repeats for an
evaluation remain together in one fold. Within each fold, the model is Scout PR
#40's L2 logistic regression: `liblinear`, `C=1.0`, `l1_ratio=0.0`,
`max_iter=1000`, and `random_state=0`.

Feature extraction matches PR #40:

- Noul values become one feature keyed by question id.
- Score probabilities become one feature per `<question>/<level>`.
- A Choice containing `none` becomes `1 - P(none)`.
- Other Choice answers, including account type, are annotations and are ignored.

Each repeat is cut at fitted probability 0.5. Two of three repeats make the
evaluation eligible. The threshold is not tuned. Out-of-fold decisions are compared
with the same human labels and frozen Scout production decisions used by the primary
report.

This is not held-out confirmation: the fold protocol was specified after the
primary answers and aggregate results were visible, and every case participates in
training four of the five models. Even a win would only nominate a frozen mapping
for a fresh randomly sampled, human-labelled confirmation cohort.
