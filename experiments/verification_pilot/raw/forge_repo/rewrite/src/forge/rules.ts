/**
 * The reasons a wait refuses an observed pull request.
 *
 * A cohort's `github_review` handoff and an epic's final integration merge
 * both wait on a pull request, and both refuse an observation for the same
 * kinds of reason: it is some other pull request, it lives in another
 * repository, it carries the wrong branches, or it did not really merge. Each
 * rule here is one such reason. A reconciler lists the rules its wait
 * applies, in the order it applies them, with the detail it records for
 * each; the first rule that fails is the mismatch.
 */
import type { ForgeRepositoryIdentity } from "../domain/epic";
import {
  parseGithubPullRequestIdentity, pullRequestMismatch, pullRequestUrlsMatch, repositoriesMatch,
  type PullRequestMismatch, type PullRequestMismatchKind, type PullRequestObservation,
} from "./pull-request";

/** What a wait expects its pull request to be. */
export interface PullRequestExpectation {
  /** The pull request the wait is on. */
  readonly url: string;
  /** Its number, when the wait recorded one apart from its URL. */
  readonly number?: number;
  /** The branch the pull request must merge from. */
  readonly head_branch: string;
  /** The branch it must merge into; null when the run declares none, and the rule is skipped. */
  readonly base_branch: string | null;
  /** The repository the run is bound to; null when it is bound to none, and the rule is skipped. */
  readonly forge_repository: ForgeRepositoryIdentity | null;
}

export type MismatchRule = (expected: PullRequestExpectation, observation: PullRequestObservation) => PullRequestMismatch | null;

type Detail = string | ((expected: PullRequestExpectation, observation: PullRequestObservation) => string);

const rule = (kind: PullRequestMismatchKind, detail: Detail, fails: (expected: PullRequestExpectation, observation: PullRequestObservation) => boolean): MismatchRule =>
  (expected, observation) => fails(expected, observation)
    ? pullRequestMismatch(kind, typeof detail === "string" ? detail : detail(expected, observation))
    : null;

/** The first rule the observation fails, or null if it passes them all. */
export const firstMismatch = (rules: readonly MismatchRule[], expected: PullRequestExpectation, observation: PullRequestObservation): PullRequestMismatch | null => {
  for (const check of rules) {
    const mismatch = check(expected, observation);
    if (mismatch) return mismatch;
  }
  return null;
};

/** The expected URL is a canonical GitHub pull request URL. */
export const canonicalExpectedUrl = (detail: Detail): MismatchRule =>
  rule("pull_request_mismatch", detail, (expected) => parseGithubPullRequestIdentity(expected.url) === null);

/** The observation is the expected pull request: same URL, and same number when one was recorded. */
export const samePullRequest = (detail: Detail): MismatchRule =>
  rule("pull_request_mismatch", detail, (expected, observation) =>
    !pullRequestUrlsMatch(expected.url, observation.url)
    || (expected.number !== undefined && expected.number !== observation.number));

/** The observation's URL names the bound repository. */
export const observedUrlInBoundRepository = (detail: Detail): MismatchRule =>
  rule("repository_mismatch", detail, (expected, observation) => {
    const identity = parseGithubPullRequestIdentity(observation.url);
    return expected.forge_repository !== null && identity !== null
      && !repositoriesMatch(identity.owner, identity.name, expected.forge_repository.owner, expected.forge_repository.name);
  });

/**
 * The observation names its repository twice — in its URL and in its own
 * fields. They have to agree, or a caller could point a merged PR's URL at
 * one repository while reporting the state of another.
 */
export const observationMatchesItsUrl = (detail: Detail): MismatchRule =>
  rule("repository_mismatch", detail, (_expected, observation) => {
    const identity = parseGithubPullRequestIdentity(observation.url);
    return identity !== null && !repositoriesMatch(observation.owner, observation.name, identity.owner, identity.name);
  });

/** The observation's own repository fields name the bound repository. */
export const observationInBoundRepository = (detail: Detail): MismatchRule =>
  rule("repository_mismatch", detail, (expected, observation) =>
    expected.forge_repository !== null
    && !repositoriesMatch(observation.owner, observation.name, expected.forge_repository.owner, expected.forge_repository.name));

export const headBranch = (detail: Detail): MismatchRule =>
  rule("head_branch_mismatch", detail, (expected, observation) => observation.head_branch !== expected.head_branch);

export const baseBranch = (detail: Detail): MismatchRule =>
  rule("base_branch_mismatch", detail, (expected, observation) =>
    expected.base_branch !== null && observation.base_branch !== expected.base_branch);

export const notClosedUnmerged = (detail: Detail): MismatchRule =>
  rule("closed_without_merge", detail, (_expected, observation) => observation.state === "closed_unmerged");

/** A merge is only evidence when it says when it merged. */
export const mergedWithEvidence = (detail: Detail): MismatchRule =>
  rule("pull_request_mismatch", detail, (_expected, observation) => observation.state === "merged" && observation.merged_at === null);
