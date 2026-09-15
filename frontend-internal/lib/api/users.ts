import { http } from "./client";
import {
  PageSchema,
  UserOut,
  type User,
  type UserCreateInput,
  type UserUpdateInput,
  type Page,
} from "./types";

export type UserListQuery = {
  page: number;
  size: number;
  full_name?: string;
  puskesmas_id?: string;
};

export async function listUsers(q: UserListQuery): Promise<Page<User>> {
  const { data } = await http.get("/users", { params: q });
  return PageSchema(UserOut).parse(data);
}

export async function createUser(input: UserCreateInput): Promise<User> {
  const { data } = await http.post("/users", input);
  return UserOut.parse(data);
}

export async function updateUser(
  id: string,
  input: UserUpdateInput,
): Promise<User> {
  const payload: Record<string, unknown> = { ...input };
  if (payload.password === "") delete payload.password;
  const { data } = await http.patch(`/users/${id}`, payload);
  return UserOut.parse(data);
}

export async function deleteUser(id: string): Promise<void> {
  await http.delete(`/users/${id}`);
}
