"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";

import { setToken, useToken } from "@/lib/auth";
import * as api from "@/lib/api";

async function login(email: string, password: string) {
  const { access_token } = await api.login(email, password);
  setToken(access_token);
}

async function register(input: Parameters<typeof api.register>[0]) {
  await api.register(input);
  await login(input.email, input.password);
}

export function useAuth() {
  const token = useToken();
  const router = useRouter();
  const queryClient = useQueryClient();

  const logout = () => {
    setToken(null);
    queryClient.clear();
    router.replace("/login");
  };

  return { token, isAuthenticated: Boolean(token), login, register, logout };
}

export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: api.getMe });
}
