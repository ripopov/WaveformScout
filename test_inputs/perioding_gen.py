#!/usr/bin/env python3
"""
Generate a VCD file with periodic signals: sine, cosine, triangular, square, sawtooth.
All signals have the same amplitude range (-1000 to 1000) but different phases and frequencies.
Also includes a clock signal with the maximum frequency of all periodic signals.
Based on signal_gen.py structure.
"""

import math
import sys
from datetime import datetime


def encode_id(n):
    """Encode a number as a VCD identifier using printable ASCII characters."""
    chars = "!\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~"
    if n == 0:
        return chars[0]

    result = ""
    while n > 0:
        result = chars[n % len(chars)] + result
        n //= len(chars)
    return result


class PeriodicVCDGenerator:
    def __init__(self, filename="periodic_signals.vcd"):
        self.filename = filename
        self.file = None
        self.time_ps = 0
        self.signals = []

    def open_file(self):
        """Open the VCD file for writing."""
        self.file = open(self.filename, 'w')

    def close_file(self):
        """Close the VCD file."""
        if self.file:
            self.file.close()

    def write_line(self, line=""):
        """Write a line to the VCD file."""
        self.file.write(line + "\n")

    def write_header(self):
        """Write the VCD header section."""
        self.write_line("$date")
        self.write_line(f"    {datetime.now().strftime('%a %b %d %H:%M:%S %Y')}")
        self.write_line("$end")
        self.write_line("$version")
        self.write_line("    Python Periodic Waveforms VCD Generator")
        self.write_line("$end")
        self.write_line("$timescale")
        self.write_line("    1ps")
        self.write_line("$end")

    def define_signals(self):
        """Define periodic signals with different frequencies and phases."""
        self.write_line("$scope module top $end")

        # Define signal configurations
        # All signals have amplitude range [-1000, 1000] but different frequencies and phases
        signal_configs = [
            {"name": "sine_1khz", "freq": 1000, "phase": 0, "wave_type": "sine", "var_type": "integer", "bitwidth": 16},
            {"name": "cosine_2khz", "freq": 2000, "phase": math.pi/2, "wave_type": "sine", "var_type": "integer", "bitwidth": 16},
            {"name": "sine_5khz", "freq": 5000, "phase": math.pi/4, "wave_type": "sine", "var_type": "integer", "bitwidth": 16},
            {"name": "cosine_10khz", "freq": 10000, "phase": 3*math.pi/4, "wave_type": "sine", "var_type": "integer", "bitwidth": 16},
            {"name": "triangle_3khz", "freq": 3000, "phase": 0, "wave_type": "triangle", "var_type": "integer", "bitwidth": 16},
            {"name": "triangle_7khz", "freq": 7000, "phase": math.pi/3, "wave_type": "triangle", "var_type": "integer", "bitwidth": 16},
            {"name": "square_1_5khz", "freq": 1500, "phase": 0, "wave_type": "square", "var_type": "integer", "bitwidth": 16},
            {"name": "square_4khz", "freq": 4000, "phase": math.pi/6, "wave_type": "square", "var_type": "integer", "bitwidth": 16},
            {"name": "sawtooth_2_5khz", "freq": 2500, "phase": 0, "wave_type": "sawtooth", "var_type": "integer", "bitwidth": 16},
            {"name": "sawtooth_6khz", "freq": 6000, "phase": math.pi/5, "wave_type": "sawtooth", "var_type": "integer", "bitwidth": 16},
        ]

        # Find maximum frequency for clock
        max_freq = max(config["freq"] for config in signal_configs)
        clock_freq = max_freq * 2  # Clock frequency is twice the maximum signal frequency

        # Add clock signal
        signal_configs.append({
            "name": "clk", 
            "freq": clock_freq, 
            "phase": 0, 
            "wave_type": "clock", 
            "var_type": "wire", 
            "bitwidth": 1
        })

        # Define all signals in VCD
        for i, config in enumerate(signal_configs):
            signal_id = encode_id(i)
            self.write_line(f"$var {config['var_type']} {config['bitwidth']} {signal_id} {config['name']} $end")

            # Store signal info for simulation
            signal_info = {
                "id": signal_id,
                "name": config["name"],
                "freq": config["freq"],
                "phase": config["phase"],
                "wave_type": config["wave_type"],
                "var_type": config["var_type"],
                "bitwidth": config["bitwidth"],
                "amp_range": [-1000, 1000],  # All signals have same amplitude range
                "last_value": None
            }
            self.signals.append(signal_info)

        self.write_line("$upscope $end")
        self.write_line("$enddefinitions $end")

    def calculate_signal_value(self, signal, time_sec):
        """Calculate the value of a signal at a given time based on its waveform type."""
        freq = signal["freq"]
        phase = signal["phase"]
        wave_type = signal["wave_type"]
        
        # Calculate the base waveform value
        if wave_type == "sine":
            # Sine wave (includes cosine with phase shift)
            wave_val = math.sin(2 * math.pi * freq * time_sec + phase)
        elif wave_type == "triangle":
            # Triangular wave
            t_normalized = (freq * time_sec + phase / (2 * math.pi)) % 1
            if t_normalized < 0.5:
                wave_val = 4 * t_normalized - 1  # Rising edge: -1 to 1
            else:
                wave_val = 3 - 4 * t_normalized  # Falling edge: 1 to -1
        elif wave_type == "square":
            # Square wave
            t_normalized = (freq * time_sec + phase / (2 * math.pi)) % 1
            wave_val = 1.0 if t_normalized < 0.5 else -1.0
        elif wave_type == "sawtooth":
            # Sawtooth wave (linear rise from -1 to 1, then sharp drop)
            t_normalized = (freq * time_sec + phase / (2 * math.pi)) % 1
            wave_val = 2 * t_normalized - 1  # Linear rise from -1 to 1
        elif wave_type == "clock":
            # Clock signal (simple square wave at high frequency)
            t_normalized = (freq * time_sec + phase / (2 * math.pi)) % 1
            return 1 if t_normalized < 0.5 else 0
        else:
            # Default to sine wave
            wave_val = math.sin(2 * math.pi * freq * time_sec + phase)

        # Map wave value to amplitude range [-1000, 1000]
        if wave_type != "clock":
            amp_min, amp_max = signal["amp_range"]
            mapped_val = amp_min + (wave_val + 1) / 2 * (amp_max - amp_min)
            return round(mapped_val)
        
        return wave_val

    def write_initial_values(self):
        """Write initial signal values at time 0."""
        self.write_line("#0")
        self.write_line("$dumpvars")

        for signal in self.signals:
            value = self.calculate_signal_value(signal, 0.0)
            signal["last_value"] = value

            # Format value based on signal type
            if signal["bitwidth"] == 1:
                # Single bit signals (clock)
                self.write_line(f"{int(value)}{signal['id']}")
            else:
                # Multi-bit integer signals use binary format
                if signal["var_type"] == "integer" and value < 0:
                    # For negative integers, use two's complement
                    unsigned_val = (1 << signal["bitwidth"]) + int(value)
                    bin_str = format(unsigned_val, f"0{signal['bitwidth']}b")
                else:
                    bin_str = format(int(value), "b")
                self.write_line(f"b{bin_str} {signal['id']}")

        self.write_line("$end")

    def simulate(self, duration_ms=5.0, sample_interval_ps=1000):
        """Simulate the signals over time and write value changes."""
        duration_ps = int(duration_ms * 1e9)  # Convert ms to ps

        current_time = sample_interval_ps  # Start from first sample interval
        while current_time <= duration_ps:
            time_sec = current_time * 1e-12  # Convert ps to seconds

            # Check for value changes
            changes = []
            for signal in self.signals:
                new_value = self.calculate_signal_value(signal, time_sec)
                if new_value != signal["last_value"]:
                    signal["last_value"] = new_value
                    changes.append((signal, new_value))

            # Write time stamp and changes if any occurred
            if changes:
                self.write_line(f"#{current_time}")
                for signal, value in changes:
                    # Format value based on signal type
                    if signal["bitwidth"] == 1:
                        # Single bit signals (clock)
                        self.write_line(f"{int(value)}{signal['id']}")
                    else:
                        # Multi-bit integer signals use binary format
                        if signal["var_type"] == "integer" and value < 0:
                            # For negative integers, use two's complement
                            unsigned_val = (1 << signal["bitwidth"]) + int(value)
                            bin_str = format(unsigned_val, f"0{signal['bitwidth']}b")
                        else:
                            bin_str = format(int(value), "b")
                        self.write_line(f"b{bin_str} {signal['id']}")

            current_time += sample_interval_ps

    def generate(self, duration_ms=5.0, sample_interval_ps=1000):
        """Generate the complete VCD file."""
        try:
            self.open_file()
            self.write_header()
            self.define_signals()
            self.write_initial_values()
            self.simulate(duration_ms, sample_interval_ps)
            print(f"VCD file '{self.filename}' generated successfully!")
            print(f"Contains periodic signals: sine, cosine, triangular, square, sawtooth")
            print(f"All signals have amplitude range [-1000, 1000]")
            print(f"Clock frequency: {max(s['freq'] for s in self.signals if s['wave_type'] != 'clock') * 2} Hz")
            print(f"Simulation duration: {duration_ms}ms")
            print(f"Sample interval: {sample_interval_ps}ps")
        finally:
            self.close_file()


def main():
    """Main function to generate the VCD file."""
    if len(sys.argv) > 1:
        filename = sys.argv[1]
    else:
        filename = "periodic_signals.vcd"

    generator = PeriodicVCDGenerator(filename)

    # Generate 5ms of simulation with 1ns sampling for better resolution
    generator.generate(duration_ms=5.0, sample_interval_ps=1000)


if __name__ == "__main__":
    main()