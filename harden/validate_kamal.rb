#!/usr/bin/env ruby
# frozen_string_literal: true
#
# Lightweight structural validation of the Kamal config, used by verify.sh when
# the `kamal` CLI is not installed. Not a substitute for `kamal config`, but it
# catches typos, missing keys, wrong ports, and an unpinned Kamal version.
require "yaml"

errors = []

cfg_path = "config/deploy.yml"
abort "missing #{cfg_path}" unless File.exist?(cfg_path)

cfg =
  begin
    YAML.safe_load(File.read(cfg_path), aliases: true)
  rescue StandardError => e
    abort "#{cfg_path} is not valid YAML: #{e.message}"
  end

%w[service image servers proxy builder].each do |k|
  errors << "deploy.yml missing top-level key: #{k}" unless cfg.is_a?(Hash) && cfg.key?(k)
end

errors << "proxy.app_port should be 3592 (Cerbos HTTP port)" if cfg.dig("proxy", "app_port") != 3592
errors << "proxy.healthcheck.path should be /_cerbos/health" if cfg.dig("proxy", "healthcheck", "path") != "/_cerbos/health"

dockerfile = cfg.dig("builder", "dockerfile")
if dockerfile.nil?
  errors << "builder.dockerfile not set"
elsif !File.exist?(dockerfile)
  errors << "builder.dockerfile points to a missing file: #{dockerfile}"
end

conf = "deploy/kamal/conf.yaml"
if File.exist?(conf)
  begin
    YAML.safe_load(File.read(conf))
  rescue StandardError => e
    errors << "#{conf} is not valid YAML: #{e.message}"
  end
else
  errors << "missing #{conf}"
end

if File.exist?("Gemfile")
  unless File.read("Gemfile").match?(/gem\s+["']kamal["']\s*,\s*["']2\.11\.0["']/)
    errors << "Gemfile must pin kamal to exactly 2.11.0"
  end
else
  errors << "missing Gemfile pinning kamal 2.11.0"
end

# Hub mode (optional): if the destination overlay exists, sanity-check it.
hub_overlay = "config/deploy.hub.yml"
if File.exist?(hub_overlay)
  hub =
    begin
      YAML.safe_load(File.read(hub_overlay), aliases: true)
    rescue StandardError => e
      errors << "#{hub_overlay} is not valid YAML: #{e.message}"
      nil
    end
  if hub
    if hub.dig("env", "clear", "CERBOS_CONFIG") != "/conf.hub.yaml"
      errors << "deploy.hub.yml must set env.clear.CERBOS_CONFIG=/conf.hub.yaml"
    end
    secrets = hub.dig("env", "secret") || []
    %w[CERBOS_HUB_CLIENT_ID CERBOS_HUB_CLIENT_SECRET CERBOS_HUB_WORKSPACE_SECRET].each do |s|
      errors << "deploy.hub.yml env.secret missing #{s}" unless secrets.include?(s)
    end
  end
  hub_conf = "deploy/kamal/conf.hub.yaml"
  if !File.exist?(hub_conf)
    errors << "missing #{hub_conf} (referenced by Hub mode)"
  else
    hc = (YAML.safe_load(File.read(hub_conf)) rescue nil)
    errors << "#{hub_conf} storage.driver must be 'hub'" if hc && hc.dig("storage", "driver") != "hub"
  end
end

if errors.empty?
  puts "kamal config structurally OK (service=#{cfg['service']}, image=#{cfg['image']})"
  exit 0
end

warn "Kamal config validation failed:"
errors.each { |e| warn "  - #{e}" }
exit 1
