import { z } from "zod";

export const UserSchema = z.object({
  name: z.string().min(1),
  age: z.number().int().min(0),
  roles: z.array(z.enum(["admin", "user"])),
});

export type User = z.infer<typeof UserSchema>;

export function parseUser(input: unknown): User {
  return UserSchema.parse(input);
}
