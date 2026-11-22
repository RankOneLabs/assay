// Evaluator build entry for this replay; not part of kbbl. The evaluator bundles
// src/ to check that the server and the review views still build.
export { createApp } from "../kbbl/core/server/app";
export { BriefReviewView } from "../kbbl/core/pwa/review/brief/BriefReviewView";
