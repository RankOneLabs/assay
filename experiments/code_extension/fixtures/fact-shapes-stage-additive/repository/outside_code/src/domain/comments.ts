import { z } from "zod";
import { keySchema } from "./validation.ts";
import { invalid, limitExceeded } from "./errors.ts";

/** A top-level comment has depth 0; replies nest at most this many levels below it. */
export const maxReplyDepth = 4;
export const maxCommentsPerJob = 500;
export const maxMentionsPerComment = 20;
export const maxBodyLength = 10000;

export interface Comment {
  id: string;
  jobId: string;
  parentId: string | null;
  depth: number;
  author: string;
  body: string;
  mentions: string[];
  revision: number;
  createdAt: number;
  updatedAt: number;
  deletedAt: number | null;
  deletedBy: string | null;
}

export interface CommentNode extends Comment {
  replies: CommentNode[];
}

export interface CommentVersion {
  revision: number;
  body: string;
  createdAt: number;
}

export interface Mention {
  commentId: string;
  jobId: string;
  jobTitle: string;
  author: string;
  body: string;
  createdAt: number;
  readAt: number | null;
}

export interface MentionFilter {
  unread?: boolean;
  jobId?: string;
  limit: number;
  offset: number;
}

const body = z.string().trim().min(1).max(maxBodyLength);

export const addCommentSchema = z.object({
  id: keySchema,
  body,
  parentId: keySchema.optional(),
}).strict();

export const editCommentSchema = z.object({
  body,
  expectedRevision: z.number().int().positive(),
}).strict();

export const mentionFilterSchema = z.object({
  unread: z.enum(["true", "false"]).transform(v => v === "true").optional(),
  jobId: keySchema.optional(),
  limit: z.coerce.number().int().min(1).max(100).default(25),
  offset: z.coerce.number().int().min(0).default(0),
}).strict();

export const markMentionsSchema = z.object({
  commentIds: z.array(keySchema).min(1).max(100).refine(ids => new Set(ids).size === ids.length),
  read: z.boolean().default(true),
}).strict();

// A mention starts a word: "@pat" and "(@pat)" count, "pat@example.com" and "@@pat" do not.
const mentionPattern = /(^|[^\w@.-])@([\w-]+)/g;

/**
 * Principals named in a body, in order of first appearance. Names follow the same key
 * rules as principal headers; an author mentioning themselves is not a mention.
 */
export function parseMentions(text: string, author: string): string[] {
  const names: string[] = [];
  for (const match of text.matchAll(mentionPattern)) {
    const name = match[2]!;
    if (!keySchema.safeParse(name).success) invalid(`mention @${name.slice(0, 80)}… is not a valid principal`);
    if (name !== author && !names.includes(name)) names.push(name);
  }
  if (names.length > maxMentionsPerComment) {
    limitExceeded(`a comment may mention at most ${maxMentionsPerComment} principals`);
  }
  return names;
}

/** Nest comments under their parents; siblings keep the order they were given in. */
export function buildThread(comments: readonly Comment[]): CommentNode[] {
  const nodes = new Map(comments.map(comment => [comment.id, { ...comment, replies: [] as CommentNode[] }]));
  const roots: CommentNode[] = [];
  for (const node of nodes.values()) {
    const parent = node.parentId === null ? undefined : nodes.get(node.parentId);
    (parent ? parent.replies : roots).push(node);
  }
  return roots;
}
