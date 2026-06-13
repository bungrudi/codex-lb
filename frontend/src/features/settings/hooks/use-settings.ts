import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import {
  addUpstreamProxyPoolMember,
  createExternalModelRoute,
  createExternalProvider,
  createUpstreamProxyEndpoint,
  createUpstreamProxyPool,
  deleteExternalModelRoute,
  deleteExternalProvider,
  getExternalModelRoutingAdmin,
  getSettings,
  getUpstreamProxyAdmin,
  putAccountProxyBinding,
  updateExternalModelRoute,
  updateExternalProvider,
  updateSettings,
} from "@/features/settings/api";
import type { SettingsUpdateRequest } from "@/features/settings/schemas";
import type {
  AccountProxyBindingRequest,
  ExternalModelRouteCreateRequest,
  ExternalModelRouteUpdateRequest,
  ExternalProviderCreateRequest,
  ExternalProviderUpdateRequest,
  UpstreamProxyEndpointCreateRequest,
  UpstreamProxyPoolCreateRequest,
  UpstreamProxyPoolMemberRequest,
} from "@/features/settings/schemas";

export function useSettings() {
  const queryClient = useQueryClient();

  const settingsQuery = useQuery({
    queryKey: ["settings", "detail"],
    queryFn: getSettings,
  });

  const updateSettingsMutation = useMutation({
    mutationFn: (payload: SettingsUpdateRequest) => updateSettings(payload),
    onSuccess: () => {
      toast.success("Settings saved");
      void queryClient.invalidateQueries({ queryKey: ["settings", "detail"] });
      void queryClient.invalidateQueries({ queryKey: ["settings", "upstream-proxy"] });
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to save settings");
    },
  });

  return {
    settingsQuery,
    updateSettingsMutation,
  };
}

export function useExternalModelRoutingAdmin() {
  const queryClient = useQueryClient();

  const externalRoutingQuery = useQuery({
    queryKey: ["settings", "external-model-routing"],
    queryFn: getExternalModelRoutingAdmin,
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["settings", "external-model-routing"] });
  };

  const createProviderMutation = useMutation({
    mutationFn: (payload: ExternalProviderCreateRequest) => createExternalProvider(payload),
    onSuccess: () => {
      toast.success("External provider created");
      invalidate();
    },
    onError: (error: Error) => {
      toast.error(error.message || "External provider creation failed");
    },
  });

  const updateProviderMutation = useMutation({
    mutationFn: ({ providerId, payload }: { providerId: string; payload: ExternalProviderUpdateRequest }) =>
      updateExternalProvider(providerId, payload),
    onSuccess: () => {
      toast.success("External provider saved");
      invalidate();
    },
    onError: (error: Error) => {
      toast.error(error.message || "External provider update failed");
    },
  });

  const deleteProviderMutation = useMutation({
    mutationFn: (providerId: string) => deleteExternalProvider(providerId),
    onSuccess: () => {
      toast.success("External provider deleted");
      invalidate();
    },
    onError: (error: Error) => {
      toast.error(error.message || "External provider deletion failed");
    },
  });

  const createRouteMutation = useMutation({
    mutationFn: (payload: ExternalModelRouteCreateRequest) => createExternalModelRoute(payload),
    onSuccess: () => {
      toast.success("External model route created");
      invalidate();
    },
    onError: (error: Error) => {
      toast.error(error.message || "External model route creation failed");
    },
  });

  const updateRouteMutation = useMutation({
    mutationFn: ({ routeId, payload }: { routeId: string; payload: ExternalModelRouteUpdateRequest }) =>
      updateExternalModelRoute(routeId, payload),
    onSuccess: () => {
      toast.success("External model route saved");
      invalidate();
    },
    onError: (error: Error) => {
      toast.error(error.message || "External model route update failed");
    },
  });

  const deleteRouteMutation = useMutation({
    mutationFn: (routeId: string) => deleteExternalModelRoute(routeId),
    onSuccess: () => {
      toast.success("External model route deleted");
      invalidate();
    },
    onError: (error: Error) => {
      toast.error(error.message || "External model route deletion failed");
    },
  });

  return {
    externalRoutingQuery,
    createProviderMutation,
    updateProviderMutation,
    deleteProviderMutation,
    createRouteMutation,
    updateRouteMutation,
    deleteRouteMutation,
  };
}

export function useUpstreamProxyAdmin() {
  const queryClient = useQueryClient();

  const upstreamProxyQuery = useQuery({
    queryKey: ["settings", "upstream-proxy"],
    queryFn: getUpstreamProxyAdmin,
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["settings", "upstream-proxy"] });
    void queryClient.invalidateQueries({ queryKey: ["settings", "detail"] });
  };

  const createEndpointMutation = useMutation({
    mutationFn: (payload: UpstreamProxyEndpointCreateRequest) => createUpstreamProxyEndpoint(payload),
    onSuccess: () => {
      toast.success("Proxy endpoint created");
      invalidate();
    },
    onError: (error: Error) => {
      toast.error(error.message || "Proxy endpoint creation failed");
    },
  });

  const createPoolMutation = useMutation({
    mutationFn: (payload: UpstreamProxyPoolCreateRequest) => createUpstreamProxyPool(payload),
    onSuccess: () => {
      toast.success("Proxy pool created");
      invalidate();
    },
    onError: (error: Error) => {
      toast.error(error.message || "Proxy pool creation failed");
    },
  });

  const addPoolMemberMutation = useMutation({
    mutationFn: ({ poolId, payload }: { poolId: string; payload: UpstreamProxyPoolMemberRequest }) =>
      addUpstreamProxyPoolMember(poolId, payload),
    onSuccess: () => {
      toast.success("Proxy pool member added");
      invalidate();
    },
    onError: (error: Error) => {
      toast.error(error.message || "Proxy pool update failed");
    },
  });

  const accountBindingMutation = useMutation({
    mutationFn: ({ accountId, payload }: { accountId: string; payload: AccountProxyBindingRequest }) =>
      putAccountProxyBinding(accountId, payload),
    onSuccess: () => {
      toast.success("Account proxy binding saved");
      invalidate();
    },
    onError: (error: Error) => {
      toast.error(error.message || "Account proxy binding failed");
    },
  });

  return {
    upstreamProxyQuery,
    createEndpointMutation,
    createPoolMutation,
    addPoolMemberMutation,
    accountBindingMutation,
  };
}
