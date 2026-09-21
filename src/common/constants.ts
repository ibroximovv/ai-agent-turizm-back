/**
 * Module and topic codes become directory and file names on disk, so they are
 * restricted to a slug shape. This also removes any chance of a `..` segment
 * escaping the uploads tree.
 */
export const CODE_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;

export const CODE_PATTERN_MESSAGE =
  'code may only contain letters, digits, dot, underscore and hyphen, and must start with a letter or digit';
