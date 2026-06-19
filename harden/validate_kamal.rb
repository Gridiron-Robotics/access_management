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

if errors.empty?
  puts "kamal config structurally OK (service=#{cfg['service']}, image=#{cfg['image']})"
  exit 0
end

warn "Kamal config validation failed:"
errors.each { |e| warn "  - #{e}" }
exit 1
