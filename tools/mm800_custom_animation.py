#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

from custom_animation import DEFAULT_BUDGET, TIMING_QUANTUM, CodecUnavailable, ValidationError, decode_animation
from animation_brightness import ALL_CODECS, compile_brightness, generate_firefly_document, load_animation_document, optimize_animation_document, parse_adjacency, load_track_model, optimize_track_model
from mm800_persistence_tool import MM800


def load_and_optimize(args):
    document = load_animation_document(args.input)
    return optimize_animation_document(document, timing=getattr(args, "timing", "exact"))


def print_warnings(animation):
    for warning in animation.warnings:
        locations = ", ".join(warning["locations"])
        print(f"palette-warning {warning['color']} occurrences={warning['count']} locations={locations}")


def print_analysis(animation, compilation, budget, selected):
    print(f"frames={len(animation.frames)} rendered_colors={len(animation.palette)}")
    if animation.envelope:
        print(f"base_colors={len(animation.envelope['base_palette'])}")
    print(f"timeline_entries_before={animation.original_entries} after={len(animation.entries)}")
    print(f"duration_ms_before={animation.total_before} after={animation.total_after}")
    print(f"loop={str(animation.loop).lower()} finite_end={animation.end} timing_quantum_ms={TIMING_QUANTUM}")
    print_warnings(animation)
    for candidate in compilation.candidates:
        if candidate.data is not None:
            print(f"{candidate.name}: {len(candidate.data)} bytes")
        else:
            print(f"{candidate.name}: unavailable: {candidate.reason}")
    print(f"selected={selected} required_bytes={len(compilation.data)} budget_bytes={budget} fits=true")


def main():
    parser = argparse.ArgumentParser(description="Offline MM800 custom-animation compiler and inspector")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "analyze", "compile"):
        command = subparsers.add_parser(name)
        command.add_argument("input", type=Path)
        command.add_argument("--timing", choices=("exact", "round"), default="exact")
        if name != "validate":
            command.add_argument("--encoding", choices=("auto", *ALL_CODECS), default="auto")
            command.add_argument("--budget", type=int, default=DEFAULT_BUDGET, help="assumed offline byte budget")
        if name == "compile":
            command.add_argument("--output", type=Path, required=True)
    fireflies = subparsers.add_parser("fireflies")
    fireflies.add_argument("--output", type=Path, required=True)
    fireflies.add_argument("--graph", type=Path, required=True)
    fireflies.add_argument("--seed", type=int, default=800)
    fireflies.add_argument("--duration-ms", type=int, default=5984)
    fireflies.add_argument("--max-lit", type=int, default=1)
    fireflies.add_argument("--brightness", default="0.7")
    fireflies.add_argument("--min-peak", type=float, default=0.1)
    fireflies.add_argument("--max-peak", type=float, default=0.9)
    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("input", type=Path)
    subparsers.add_parser("storage")
    device_storage = subparsers.add_parser("device-storage")
    device_storage.add_argument("--device", default="auto")
    install_parser = subparsers.add_parser("install")
    install_parser.add_argument("input", type=Path)
    install_parser.add_argument("--device", default="auto")
    install_parser.add_argument("--encoding", choices=("auto", *ALL_CODECS), default="auto")
    install_parser.add_argument("--timing", choices=("exact", "round"), default="exact")
    args = parser.parse_args()

    if args.command == "storage":
        print("profile=eeprom-ab assumed_offline_only=true")
        print("banks=2 bank_bytes=1792 bank_header_bytes=64 usable_animation_bytes=1728")
        print(f"format_version=1 codecs={','.join(ALL_CODECS)}")
        print("This is a proposed layout, not a queried or validated hardware capability.")
        return
    if args.command == "device-storage":
        with MM800(args.device) as mm800:
            print(mm800.custom_capabilities())
        return
    if args.command == "fireflies":
        adjacency = parse_adjacency(json.loads(args.graph.read_text()))
        palette = {"gold": "#ffd040", "lemon": "#fff080"}
        document = generate_firefly_document(args.seed, args.duration_ms, palette, adjacency, args.max_lit, args.brightness, args.min_peak, args.max_peak)
        animation = optimize_track_model(load_track_model(document))
        if args.output.exists():
            raise ValidationError(f"refusing to overwrite {args.output}")
        args.output.write_text(json.dumps(document, indent=2) + "\n")
        print(f"wrote={args.output} tracks={len(document['tracks'])} base_colors={len(animation.envelope['base_palette'])}")
        return
    if args.command == "inspect":
        data = args.input.read_bytes()
        frames, entries, loop, end = decode_animation(data)
        print(f"bytes={len(data)} timeline_entries={len(entries)} duration_ticks={sum(entry.duration for entry in entries)}")
        print(f"loop={str(loop).lower()} finite_end={end}")
        print(f"first_frame={frames[entries[0].frame].hex()}")
        print(f"last_frame={frames[entries[-1].frame].hex()}")
        return
    if args.command == "validate":
        animation = load_and_optimize(args)
        print(f"valid=true frames={len(animation.frames)} colors={len(animation.palette)} timeline_entries={len(animation.entries)}")
        print_warnings(animation)
        return

    animation = load_and_optimize(args)
    if args.budget <= 0:
        raise ValidationError("budget must be positive")
    compilation = compile_brightness(animation, args.encoding, args.budget)
    print_analysis(animation, compilation, args.budget, compilation.selected)
    if args.command == "compile":
        if args.output.exists():
            raise ValidationError(f"refusing to overwrite {args.output}")
        frames, entries, loop, end = decode_animation(compilation.data)
        expected = [(animation.frames[entry.frame], entry.duration) for entry in animation.entries]
        actual = [(frames[entry.frame], entry.duration) for entry in entries]
        if actual != expected or loop != animation.loop or end != animation.end:
            raise ValidationError("internal round-trip verification failed")
        args.output.write_bytes(compilation.data)
        print(f"wrote={args.output} round_trip=exact")
    elif args.command == "install":
        with MM800(args.device) as mm800:
            committed = mm800.install_custom_animation(compilation.data)
        print(f"installed_codec={compilation.selected} bytes={len(compilation.data)} generation={committed['generation']} verified=true")


if __name__ == "__main__":
    try:
        main()
    except (ValidationError, CodecUnavailable, OSError) as error:
        raise SystemExit(f"error: {error}")
