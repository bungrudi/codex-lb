import { useMemo, useState } from "react";
import { Network } from "lucide-react";

import { AlertMessage } from "@/components/alert-message";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import type {
  ExternalModelRouteCreateRequest,
  ExternalModelRouteUpdateRequest,
  ExternalModelRoutingAdmin,
  ExternalProviderCreateRequest,
  ExternalProviderUpdateRequest,
  ExternalRouteEndpoint,
} from "@/features/settings/schemas";

const ROUTE_ENDPOINTS: Array<{ value: ExternalRouteEndpoint; label: string }> = [
  { value: "chat.completions", label: "Chat completions" },
  { value: "responses", label: "Responses" },
  { value: "backend.responses", label: "Codex backend Responses" },
  { value: "responses.compact", label: "Compact" },
  { value: "responses.websocket", label: "WebSocket" },
];

export type ExternalModelRoutingSettingsProps = {
  admin: ExternalModelRoutingAdmin;
  busy: boolean;
  onCreateProvider: (payload: ExternalProviderCreateRequest) => Promise<unknown>;
  onUpdateProvider: (providerId: string, payload: ExternalProviderUpdateRequest) => Promise<unknown>;
  onDeleteProvider: (providerId: string) => Promise<unknown>;
  onCreateRoute: (payload: ExternalModelRouteCreateRequest) => Promise<unknown>;
  onUpdateRoute: (publicModel: string, payload: ExternalModelRouteUpdateRequest) => Promise<unknown>;
  onDeleteRoute: (publicModel: string) => Promise<unknown>;
};

function statusVariant(status: string): "default" | "secondary" | "destructive" | "outline" {
  if (status === "active") {
    return "default";
  }
  if (status === "disabled") {
    return "secondary";
  }
  if (status === "missing_api_key" || status === "provider_disabled") {
    return "destructive";
  }
  return "outline";
}

function secretLabel(source: string): string {
  if (source === "dashboard") {
    return "Key stored";
  }
  if (source === "env") {
    return "Env key";
  }
  return "Missing key";
}

export function ExternalModelRoutingSettings({
  admin,
  busy,
  onCreateProvider,
  onUpdateProvider,
  onDeleteProvider,
  onCreateRoute,
  onUpdateRoute,
  onDeleteRoute,
}: ExternalModelRoutingSettingsProps) {
  const [providerId, setProviderId] = useState("openrouter");
  const [providerBaseUrl, setProviderBaseUrl] = useState("https://openrouter.ai/api/v1");
  const [providerApiKey, setProviderApiKey] = useState("");
  const [providerApiKeyEnv, setProviderApiKeyEnv] = useState("");
  const [providerKeyUpdates, setProviderKeyUpdates] = useState<Record<string, string>>({});
  const [routeName, setRouteName] = useState("Minimax Codex");
  const [publicModel, setPublicModel] = useState("gpt-5.3-codex");
  const [routeProviderId, setRouteProviderId] = useState(admin.providers[0]?.id ?? "");
  const [targetModel, setTargetModel] = useState("minimax/minimax-m3");
  const [selectedEndpoints, setSelectedEndpoints] = useState<Set<ExternalRouteEndpoint>>(
    () => new Set(["chat.completions", "responses", "backend.responses"]),
  );
  const [routeTargetUpdates, setRouteTargetUpdates] = useState<Record<string, string>>({});
  const activeRows = admin.routes
    .filter((route) => route.isActive)
    .flatMap((route) => route.endpoints.map((endpoint) => ({ route, endpoint })));

  const providerIdValue = providerId.trim().toLowerCase();
  const providerValid = providerIdValue.length > 0 && providerBaseUrl.trim().length > 0;
  const routeProviderValue = routeProviderId || admin.providers[0]?.id || "";
  const routeValid =
    routeName.trim().length > 0 &&
    publicModel.trim().length > 0 &&
    routeProviderValue.length > 0 &&
    targetModel.trim().length > 0 &&
    selectedEndpoints.size > 0;
  const existingProviderIds = useMemo(() => new Set(admin.providers.map((provider) => provider.id)), [admin.providers]);
  const createProviderMode = !existingProviderIds.has(providerIdValue);

  const toggleEndpoint = (endpoint: ExternalRouteEndpoint, checked: boolean) => {
    setSelectedEndpoints((current) => {
      const next = new Set(current);
      if (checked) {
        next.add(endpoint);
      } else {
        next.delete(endpoint);
      }
      return next;
    });
  };

  const submitProvider = async () => {
    if (!providerValid) {
      return;
    }
    await onCreateProvider({
      id: providerIdValue,
      kind: "openai_compatible",
      baseUrl: providerBaseUrl.trim(),
      apiKey: providerApiKey.trim() || null,
      apiKeyEnv: providerApiKeyEnv.trim() || null,
      defaultHeaders: {},
      timeoutSeconds: 600,
      streamIdleTimeoutSeconds: 600,
      isActive: true,
      allowInsecureBaseUrl: false,
    });
    setProviderApiKey("");
  };

  const submitRoute = async () => {
    if (!routeValid) {
      return;
    }
    await onCreateRoute({
      name: routeName.trim(),
      publicModel: publicModel.trim(),
      providerId: routeProviderValue,
      targetModel: targetModel.trim(),
      endpoints: [...selectedEndpoints],
      preservePublicModel: true,
      fallbackToCodexPool: false,
      isActive: true,
      requestOverrides: {},
      stripRequestFields: [],
      deactivateConflicts: true,
    });
  };

  return (
    <section className="rounded-xl border bg-card p-5">
      <div className="space-y-4">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10">
              <Network className="h-4 w-4 text-primary" aria-hidden="true" />
            </div>
            <div>
              <h3 className="text-sm font-semibold">External model routing</h3>
              <p className="text-xs text-muted-foreground">
                Map public GPT/Codex model names to OpenAI-compatible providers without exposing target model ids.
              </p>
            </div>
          </div>
        </div>

        <AlertMessage variant="warning">
          External routes send prompts, tool context, and attachments to the configured third-party provider. Public
          model names stay visible to clients; provider ids and target models remain operator-only.
        </AlertMessage>

        <div className="grid gap-3 lg:grid-cols-2">
          <div className="space-y-2 rounded-lg border p-3">
            <p className="text-sm font-medium">Create provider</p>
            <Input aria-label="External provider id" className="h-8 text-xs" value={providerId} disabled={busy} onChange={(event) => setProviderId(event.target.value)} />
            <Input aria-label="External provider base URL" className="h-8 text-xs" value={providerBaseUrl} disabled={busy} onChange={(event) => setProviderBaseUrl(event.target.value)} />
            <Input aria-label="External provider API key" className="h-8 text-xs" type="password" placeholder="API key (stored encrypted)" value={providerApiKey} disabled={busy} onChange={(event) => setProviderApiKey(event.target.value)} />
            <Input aria-label="External provider API key env" className="h-8 text-xs" placeholder="Optional env fallback, e.g. OPENROUTER_API_KEY" value={providerApiKeyEnv} disabled={busy} onChange={(event) => setProviderApiKeyEnv(event.target.value)} />
            {!createProviderMode ? <p className="text-xs text-muted-foreground">Provider id already exists.</p> : null}
            <Button type="button" size="sm" className="h-8 w-full text-xs" disabled={busy || !providerValid || !createProviderMode} onClick={() => void submitProvider()}>
              Create provider
            </Button>
          </div>

          <div className="space-y-2 rounded-lg border p-3">
            <p className="text-sm font-medium">Create route profile</p>
            <Input aria-label="External route profile name" className="h-8 text-xs" value={routeName} disabled={busy} onChange={(event) => setRouteName(event.target.value)} />
            <Input aria-label="External route public model" className="h-8 text-xs" value={publicModel} disabled={busy} onChange={(event) => setPublicModel(event.target.value)} />
            <Select value={routeProviderValue} onValueChange={setRouteProviderId} disabled={busy || admin.providers.length === 0}>
              <SelectTrigger className="h-8 text-xs" aria-label="External route provider"><SelectValue placeholder="Select provider" /></SelectTrigger>
              <SelectContent>{admin.providers.map((provider) => <SelectItem key={provider.id} value={provider.id}>{provider.id}</SelectItem>)}</SelectContent>
            </Select>
            <Input aria-label="External route target model" className="h-8 text-xs" value={targetModel} disabled={busy} onChange={(event) => setTargetModel(event.target.value)} />
            <div className="grid gap-2 rounded-md border p-2 sm:grid-cols-2">
              {ROUTE_ENDPOINTS.map((endpoint) => (
                <label key={endpoint.value} className="flex items-center gap-2 text-xs">
                  <Checkbox checked={selectedEndpoints.has(endpoint.value)} disabled={busy} onCheckedChange={(checked) => toggleEndpoint(endpoint.value, checked === true)} />
                  <span>{endpoint.label}</span>
                </label>
              ))}
            </div>
            <Button type="button" size="sm" className="h-8 w-full text-xs" disabled={busy || !routeValid} onClick={() => void submitRoute()}>
              Create route profile
            </Button>
          </div>
        </div>

        <div className="grid gap-3 xl:grid-cols-2">
          <div className="rounded-lg border p-3">
            <p className="text-sm font-medium">Providers</p>
            <div className="mt-2 space-y-2">
              {admin.providers.length === 0 ? <p className="text-xs text-muted-foreground">No external providers configured.</p> : null}
              {admin.providers.map((provider) => {
                const keyDraft = providerKeyUpdates[provider.id] ?? "";
                return (
                  <div key={provider.id} className="space-y-2 rounded-md bg-muted/50 p-2 text-xs">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <p className="font-medium text-foreground">{provider.id}</p>
                        <p className="text-muted-foreground">{provider.baseUrl}</p>
                      </div>
                      <div className="flex items-center gap-2">
                        <Badge variant={provider.apiKeyConfigured ? "secondary" : "destructive"}>{secretLabel(provider.apiKeySource)}</Badge>
                        <Switch aria-label={`Enable external provider ${provider.id}`} checked={provider.isActive} disabled={busy} onCheckedChange={(checked) => void onUpdateProvider(provider.id, { isActive: checked })} />
                      </div>
                    </div>
                    <div className="flex flex-col gap-2 sm:flex-row">
                      <Input aria-label={`API key for external provider ${provider.id}`} className="h-8 text-xs" type="password" placeholder="New API key" value={keyDraft} disabled={busy} onChange={(event) => setProviderKeyUpdates((current) => ({ ...current, [provider.id]: event.target.value }))} />
                      <Button type="button" size="sm" variant="outline" className="h-8 text-xs" disabled={busy || keyDraft.trim().length === 0} onClick={() => void onUpdateProvider(provider.id, { apiKey: keyDraft.trim() }).then(() => setProviderKeyUpdates((current) => ({ ...current, [provider.id]: "" })))}>
                        Update key
                      </Button>
                      <Button type="button" size="sm" variant="outline" className="h-8 text-xs" disabled={busy || !provider.apiKeyConfigured} onClick={() => void onUpdateProvider(provider.id, { clearApiKey: true })}>
                        Clear key
                      </Button>
                      <Button type="button" size="sm" variant="destructive" className="h-8 text-xs" disabled={busy} onClick={() => void onDeleteProvider(provider.id)}>
                        Delete
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="space-y-3 rounded-lg border p-3">
            <div>
              <p className="text-sm font-medium">Active map</p>
              <div className="mt-2 space-y-1 text-xs text-muted-foreground">
                {activeRows.length === 0 ? <p>No active external routes.</p> : null}
                {activeRows.map(({ route, endpoint }) => (
                  <p key={`${route.id}:${endpoint}`}>
                    <span className="font-medium text-foreground">{route.publicModel}</span> · {endpoint} · {route.name} → {route.targetModel}
                  </p>
                ))}
              </div>
            </div>

            <div>
              <p className="text-sm font-medium">Route profiles</p>
              <div className="mt-2 space-y-2">
                {admin.routes.length === 0 ? <p className="text-xs text-muted-foreground">No external route profiles configured.</p> : null}
                {admin.routes.map((route) => {
                  const retargetDraft = routeTargetUpdates[route.id] ?? route.targetModel;
                  return (
                    <div key={route.id} className="space-y-2 rounded-md bg-muted/50 p-2 text-xs">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div>
                          <p className="font-medium text-foreground">{route.name}</p>
                          <p className="text-muted-foreground">{route.publicModel} · {route.providerId} → {route.targetModel}</p>
                          <p className="text-muted-foreground">{route.endpoints.join(", ")}</p>
                        </div>
                        <div className="flex items-center gap-2">
                          <Badge variant={statusVariant(route.status)}>{route.status.replaceAll("_", " ")}</Badge>
                          <Switch aria-label={`Enable external route ${route.name}`} checked={route.isActive} disabled={busy} onCheckedChange={(checked) => void onUpdateRoute(route.id, { isActive: checked, deactivateConflicts: true })} />
                        </div>
                      </div>
                      {route.statusMessage ? <AlertMessage variant="warning">{route.statusMessage}</AlertMessage> : null}
                      <div className="flex flex-col gap-2 sm:flex-row">
                        <Input aria-label={`Target model for external route ${route.name}`} className="h-8 text-xs" value={retargetDraft} disabled={busy} onChange={(event) => setRouteTargetUpdates((current) => ({ ...current, [route.id]: event.target.value }))} />
                        <Button type="button" size="sm" variant="outline" className="h-8 text-xs" disabled={busy || retargetDraft.trim().length === 0 || retargetDraft.trim() === route.targetModel} onClick={() => void onUpdateRoute(route.id, { targetModel: retargetDraft.trim(), deactivateConflicts: true })}>
                          Retarget
                        </Button>
                        <Button type="button" size="sm" variant="destructive" className="h-8 text-xs" disabled={busy} onClick={() => void onDeleteRoute(route.id)}>
                          Delete
                        </Button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
