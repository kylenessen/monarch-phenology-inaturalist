#!/usr/bin/env python3
"""
GBIF Taxa Analysis Tool

A general-purpose tool for querying GBIF taxonomic data and generating
visualizations and statistics about how different taxonomic groups
represent percentages of total biodiversity.

Usage:
    python gbif_taxa_analysis.py --rank ORDER --compare Lepidoptera,Coleoptera,Diptera
    python gbif_taxa_analysis.py --rank CLASS --top 10
    python gbif_taxa_analysis.py --rank PHYLUM --all
"""

import argparse
import json
import os
import sys
import warnings
from typing import Dict, List, Optional, Tuple
from datetime import datetime

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from matplotlib.patches import Rectangle

# Disable SSL warnings (for environments with SSL issues)
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Set style for better-looking plots
sns.set_style("whitegrid")
plt.rcParams['figure.figsize'] = (14, 8)


class GBIFTaxaAnalyzer:
    """Analyzer for GBIF taxonomic data with visualization capabilities."""

    BASE_URL = "https://api.gbif.org/v1"

    def __init__(self, output_dir: str = "output", verify_ssl: bool = False):
        """Initialize the analyzer.

        Args:
            output_dir: Directory to save output files
            verify_ssl: Whether to verify SSL certificates (default: False for compatibility)
        """
        self.output_dir = output_dir
        self.verify_ssl = verify_ssl
        os.makedirs(output_dir, exist_ok=True)

        # Create a session with retry logic
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def get_species_count_for_taxon(self, taxon_name: str, rank: str = "ORDER") -> Optional[int]:
        """Get the number of accepted species for a specific taxon.

        Args:
            taxon_name: Name of the taxon (e.g., "Lepidoptera")
            rank: Taxonomic rank (e.g., "ORDER", "CLASS", "PHYLUM")

        Returns:
            Number of species, or None if not found
        """
        # First, get the taxon key
        url = f"{self.BASE_URL}/species/match"
        params = {
            "name": taxon_name,
            "rank": rank
        }

        try:
            response = self.session.get(url, params=params, timeout=30, verify=self.verify_ssl)
            response.raise_for_status()
            data = response.json()

            if "usageKey" not in data:
                print(f"Warning: Could not find taxon '{taxon_name}' at rank {rank}")
                return None

            taxon_key = data["usageKey"]

            # Now search for species under this taxon
            search_url = f"{self.BASE_URL}/species/search"
            search_params = {
                "highertaxonKey": taxon_key,
                "rank": "SPECIES",
                "status": "ACCEPTED",
                "limit": 0  # We only want the count
            }

            search_response = self.session.get(search_url, params=search_params, timeout=30, verify=self.verify_ssl)
            search_response.raise_for_status()
            search_data = search_response.json()

            count = search_data.get("count", 0)
            print(f"Found {count:,} species in {taxon_name} ({rank})")

            return count

        except requests.exceptions.RequestException as e:
            print(f"Error querying GBIF for {taxon_name}: {e}")
            return None

    def get_all_taxa_at_rank(self, rank: str = "ORDER", limit: int = 1000) -> List[Dict]:
        """Get all taxa at a specific rank with their species counts.

        Args:
            rank: Taxonomic rank (e.g., "ORDER", "CLASS", "PHYLUM")
            limit: Maximum number of taxa to retrieve

        Returns:
            List of dictionaries with taxon information
        """
        url = f"{self.BASE_URL}/species/search"
        params = {
            "rank": rank,
            "status": "ACCEPTED",
            "limit": min(limit, 1000),
            "offset": 0
        }

        all_taxa = []

        try:
            while True:
                print(f"Fetching taxa at rank {rank}, offset {params['offset']}...")
                response = self.session.get(url, params=params, timeout=30, verify=self.verify_ssl)
                response.raise_for_status()
                data = response.json()

                results = data.get("results", [])
                if not results:
                    break

                for taxon in results:
                    taxon_info = {
                        "name": taxon.get("canonicalName", taxon.get("scientificName", "Unknown")),
                        "key": taxon.get("key"),
                        "rank": taxon.get("rank"),
                        "numDescendants": taxon.get("numDescendants", 0),
                        "kingdom": taxon.get("kingdom", "Unknown")
                    }
                    all_taxa.append(taxon_info)

                # Check if we've retrieved all results
                if params["offset"] + params["limit"] >= data.get("count", 0):
                    break

                params["offset"] += params["limit"]

                # Limit total results
                if len(all_taxa) >= limit:
                    break

            print(f"Retrieved {len(all_taxa)} taxa at rank {rank}")
            return all_taxa

        except requests.exceptions.RequestException as e:
            print(f"Error querying GBIF: {e}")
            return []

    def get_species_counts_for_taxa(self, taxa_names: List[str], rank: str = "ORDER") -> Dict[str, int]:
        """Get species counts for multiple taxa.

        Args:
            taxa_names: List of taxon names
            rank: Taxonomic rank

        Returns:
            Dictionary mapping taxon names to species counts
        """
        counts = {}

        for taxon_name in taxa_names:
            count = self.get_species_count_for_taxon(taxon_name, rank)
            if count is not None:
                counts[taxon_name] = count

        return counts

    def get_total_species_count(self, use_catalogue_of_life: bool = True) -> int:
        """Get the total number of accepted species.

        Args:
            use_catalogue_of_life: If True, use Catalogue of Life 2025 estimate (2.2M species)
                                   If False, query GBIF (may include synonyms and be inflated)

        Returns:
            Total species count
        """
        if use_catalogue_of_life:
            # Catalogue of Life 2025 estimate: ~2.2 million accepted species
            # Source: https://www.catalogueoflife.org/
            total = 2_200_000
            print(f"Using Catalogue of Life 2025 estimate: {total:,} accepted species")
            print(f"(This is more accurate than GBIF's count which includes synonyms)")
            return total

        # Otherwise query GBIF (may be inflated)
        url = f"{self.BASE_URL}/species/search"
        params = {
            "rank": "SPECIES",
            "status": "ACCEPTED",
            "limit": 0
        }

        try:
            response = self.session.get(url, params=params, timeout=30, verify=self.verify_ssl)
            response.raise_for_status()
            data = response.json()

            total = data.get("count", 0)
            print(f"Total accepted species in GBIF: {total:,}")
            print(f"Warning: This count may be inflated as it includes synonyms and infraspecific taxa")

            return total

        except requests.exceptions.RequestException as e:
            print(f"Error querying GBIF for total species: {e}")
            return 0

    def calculate_percentages(self, counts: Dict[str, int], total: int) -> Dict[str, float]:
        """Calculate percentages of total for each taxon.

        Args:
            counts: Dictionary of taxon counts
            total: Total count

        Returns:
            Dictionary mapping taxon names to percentages
        """
        percentages = {}

        for taxon, count in counts.items():
            if total > 0:
                percentages[taxon] = (count / total) * 100
            else:
                percentages[taxon] = 0.0

        return percentages

    def create_pie_chart(self, data: Dict[str, int], title: str,
                        filename: str, show_other: bool = True) -> None:
        """Create a pie chart visualization.

        Args:
            data: Dictionary mapping labels to values
            title: Chart title
            filename: Output filename
            show_other: Whether to group small percentages into "Other"
        """
        total = sum(data.values())

        # Sort by value
        sorted_data = dict(sorted(data.items(), key=lambda x: x[1], reverse=True))

        # Optionally group small percentages
        if show_other and len(sorted_data) > 10:
            top_items = dict(list(sorted_data.items())[:9])
            other_sum = sum(list(sorted_data.values())[9:])
            if other_sum > 0:
                top_items["Other"] = other_sum
            sorted_data = top_items

        # Calculate percentages
        percentages = [(v / total * 100) for v in sorted_data.values()]

        # Create pie chart
        fig, ax = plt.subplots(figsize=(12, 8))

        colors = sns.color_palette("husl", len(sorted_data))
        wedges, texts, autotexts = ax.pie(
            sorted_data.values(),
            labels=sorted_data.keys(),
            autopct='%1.1f%%',
            startangle=90,
            colors=colors,
            textprops={'fontsize': 10}
        )

        # Make percentage text bold
        for autotext in autotexts:
            autotext.set_color('white')
            autotext.set_fontweight('bold')

        ax.set_title(title, fontsize=16, fontweight='bold', pad=20)

        plt.tight_layout()
        filepath = os.path.join(self.output_dir, filename)
        plt.savefig(filepath, dpi=300, bbox_inches='tight')
        print(f"Saved pie chart to {filepath}")
        plt.close()

    def create_bar_chart(self, data: Dict[str, int], title: str,
                        filename: str, top_n: Optional[int] = None) -> None:
        """Create a horizontal bar chart visualization.

        Args:
            data: Dictionary mapping labels to values
            title: Chart title
            filename: Output filename
            top_n: Show only top N items
        """
        # Sort by value
        sorted_data = dict(sorted(data.items(), key=lambda x: x[1], reverse=True))

        if top_n:
            sorted_data = dict(list(sorted_data.items())[:top_n])

        # Create bar chart
        fig, ax = plt.subplots(figsize=(12, max(8, len(sorted_data) * 0.5)))

        taxa = list(sorted_data.keys())
        counts = list(sorted_data.values())

        colors = sns.color_palette("viridis", len(taxa))
        bars = ax.barh(taxa, counts, color=colors)

        # Add value labels on bars
        for i, (bar, count) in enumerate(zip(bars, counts)):
            width = bar.get_width()
            ax.text(width, bar.get_y() + bar.get_height()/2,
                   f' {count:,}',
                   ha='left', va='center', fontweight='bold')

        ax.set_xlabel('Number of Species', fontsize=12, fontweight='bold')
        ax.set_title(title, fontsize=16, fontweight='bold', pad=20)
        ax.invert_yaxis()

        plt.tight_layout()
        filepath = os.path.join(self.output_dir, filename)
        plt.savefig(filepath, dpi=300, bbox_inches='tight')
        print(f"Saved bar chart to {filepath}")
        plt.close()

    def create_comparison_chart(self, data: Dict[str, int], total: int,
                               title: str, filename: str) -> None:
        """Create a comparison chart showing both counts and percentages.

        Args:
            data: Dictionary mapping labels to values
            total: Total count for percentage calculation
            title: Chart title
            filename: Output filename
        """
        # Sort by value
        sorted_data = dict(sorted(data.items(), key=lambda x: x[1], reverse=True))

        taxa = list(sorted_data.keys())
        counts = list(sorted_data.values())
        percentages = [(c / total * 100) for c in counts]

        # Create figure with two subplots
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, max(8, len(taxa) * 0.5)))

        colors = sns.color_palette("Set2", len(taxa))

        # Bar chart for counts
        bars1 = ax1.barh(taxa, counts, color=colors)
        for bar, count in zip(bars1, counts):
            width = bar.get_width()
            ax1.text(width, bar.get_y() + bar.get_height()/2,
                    f' {count:,}',
                    ha='left', va='center', fontweight='bold', fontsize=9)

        ax1.set_xlabel('Number of Species', fontsize=11, fontweight='bold')
        ax1.set_title('Species Counts', fontsize=13, fontweight='bold')
        ax1.invert_yaxis()

        # Bar chart for percentages
        bars2 = ax2.barh(taxa, percentages, color=colors)
        for bar, pct in zip(bars2, percentages):
            width = bar.get_width()
            ax2.text(width, bar.get_y() + bar.get_height()/2,
                    f' {pct:.2f}%',
                    ha='left', va='center', fontweight='bold', fontsize=9)

        ax2.set_xlabel('Percentage of Total Species', fontsize=11, fontweight='bold')
        ax2.set_title('Percentage of Total Diversity', fontsize=13, fontweight='bold')
        ax2.invert_yaxis()

        fig.suptitle(title, fontsize=16, fontweight='bold', y=1.02)

        plt.tight_layout()
        filepath = os.path.join(self.output_dir, filename)
        plt.savefig(filepath, dpi=300, bbox_inches='tight')
        print(f"Saved comparison chart to {filepath}")
        plt.close()

    def generate_statistics_report(self, counts: Dict[str, int],
                                   total: int, rank: str,
                                   filename: str = "statistics_report.txt") -> None:
        """Generate a text report with statistics.

        Args:
            counts: Dictionary of taxon counts
            total: Total species count
            rank: Taxonomic rank
            filename: Output filename
        """
        percentages = self.calculate_percentages(counts, total)
        sorted_taxa = sorted(counts.items(), key=lambda x: x[1], reverse=True)

        filepath = os.path.join(self.output_dir, filename)

        with open(filepath, 'w') as f:
            f.write("=" * 80 + "\n")
            f.write("GBIF TAXONOMIC DIVERSITY ANALYSIS REPORT\n")
            f.write("=" * 80 + "\n\n")

            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Taxonomic Rank: {rank}\n")
            f.write(f"Total Accepted Species in GBIF: {total:,}\n")
            f.write(f"Number of {rank} analyzed: {len(counts)}\n\n")

            f.write("-" * 80 + "\n")
            f.write("DETAILED BREAKDOWN\n")
            f.write("-" * 80 + "\n\n")

            for i, (taxon, count) in enumerate(sorted_taxa, 1):
                pct = percentages[taxon]
                f.write(f"{i:3d}. {taxon:30s} : {count:10,} species ({pct:6.2f}%)\n")

            f.write("\n" + "=" * 80 + "\n")
            f.write("SUMMARY STATISTICS\n")
            f.write("=" * 80 + "\n\n")

            accounted_total = sum(counts.values())
            accounted_pct = (accounted_total / total * 100) if total > 0 else 0

            f.write(f"Species in analyzed {rank}: {accounted_total:,}\n")
            f.write(f"Percentage of total diversity: {accounted_pct:.2f}%\n")
            f.write(f"Mean species per {rank}: {accounted_total / len(counts):,.0f}\n")
            f.write(f"Median species per {rank}: {sorted(counts.values())[len(counts)//2]:,}\n")

            if len(sorted_taxa) > 0:
                f.write(f"\nLargest {rank}: {sorted_taxa[0][0]} ({sorted_taxa[0][1]:,} species, "
                       f"{percentages[sorted_taxa[0][0]]:.2f}%)\n")
                f.write(f"Smallest {rank}: {sorted_taxa[-1][0]} ({sorted_taxa[-1][1]:,} species, "
                       f"{percentages[sorted_taxa[-1][0]]:.2f}%)\n")

            # Special note for Lepidoptera if present
            if "Lepidoptera" in percentages:
                f.write("\n" + "=" * 80 + "\n")
                f.write("LEPIDOPTERA ANALYSIS (Moths and Butterflies)\n")
                f.write("=" * 80 + "\n\n")
                f.write(f"Species count: {counts['Lepidoptera']:,}\n")
                f.write(f"Percentage of total diversity: {percentages['Lepidoptera']:.2f}%\n")
                f.write(f"\nNote: This represents {'approximately' if 8 < percentages['Lepidoptera'] < 12 else 'about'} "
                       f"{percentages['Lepidoptera']:.1f}% of all described\n")
                f.write(f"species on Earth, {'confirming' if 8 < percentages['Lepidoptera'] < 12 else 'differing from'} "
                       f"the expected ~10% figure.\n")

        print(f"Saved statistics report to {filepath}")

        # Also print key findings to console
        print("\n" + "=" * 80)
        print("KEY FINDINGS")
        print("=" * 80)
        print(f"Total species analyzed: {accounted_total:,} ({accounted_pct:.2f}% of GBIF total)")
        if len(sorted_taxa) > 0:
            print(f"Largest {rank}: {sorted_taxa[0][0]} with {sorted_taxa[0][1]:,} species "
                  f"({percentages[sorted_taxa[0][0]]:.2f}%)")
        if "Lepidoptera" in percentages:
            print(f"\nLepidoptera (moths & butterflies): {counts['Lepidoptera']:,} species "
                  f"({percentages['Lepidoptera']:.2f}% of total)")
        print("=" * 80 + "\n")

    def save_data_to_csv(self, counts: Dict[str, int], total: int,
                         filename: str = "taxa_data.csv") -> None:
        """Save the data to a CSV file.

        Args:
            counts: Dictionary of taxon counts
            total: Total species count
            filename: Output filename
        """
        percentages = self.calculate_percentages(counts, total)

        df = pd.DataFrame({
            'Taxon': list(counts.keys()),
            'Species_Count': list(counts.values()),
            'Percentage': [percentages[taxon] for taxon in counts.keys()]
        })

        df = df.sort_values('Species_Count', ascending=False)
        df['Rank'] = range(1, len(df) + 1)
        df = df[['Rank', 'Taxon', 'Species_Count', 'Percentage']]

        filepath = os.path.join(self.output_dir, filename)
        df.to_csv(filepath, index=False)
        print(f"Saved data to {filepath}")


def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description="Analyze GBIF taxonomic data and generate visualizations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Compare specific orders
  python gbif_taxa_analysis.py --rank ORDER --compare Lepidoptera,Coleoptera,Diptera,Hymenoptera

  # Analyze top 10 orders
  python gbif_taxa_analysis.py --rank ORDER --top 10

  # Analyze all classes
  python gbif_taxa_analysis.py --rank CLASS --all

  # Analyze specific Lepidoptera with custom output
  python gbif_taxa_analysis.py --rank ORDER --compare Lepidoptera --output lepidoptera_analysis
        """
    )

    parser.add_argument(
        '--rank',
        type=str,
        default='ORDER',
        choices=['ORDER', 'CLASS', 'PHYLUM', 'FAMILY', 'KINGDOM'],
        help='Taxonomic rank to analyze (default: ORDER)'
    )

    parser.add_argument(
        '--compare',
        type=str,
        help='Comma-separated list of taxa to compare (e.g., Lepidoptera,Coleoptera)'
    )

    parser.add_argument(
        '--top',
        type=int,
        help='Analyze top N taxa by species count'
    )

    parser.add_argument(
        '--all',
        action='store_true',
        help='Analyze all taxa at the specified rank (warning: may be slow)'
    )

    parser.add_argument(
        '--output',
        type=str,
        default='output',
        help='Output directory for results (default: output)'
    )

    parser.add_argument(
        '--use-gbif-total',
        action='store_true',
        help='Use GBIF total count instead of Catalogue of Life estimate (may be inflated)'
    )

    args = parser.parse_args()

    # Validate arguments
    if not any([args.compare, args.top, args.all]):
        parser.error("Must specify one of: --compare, --top, or --all")

    # Initialize analyzer
    analyzer = GBIFTaxaAnalyzer(output_dir=args.output)

    print("\n" + "=" * 80)
    print("GBIF TAXONOMIC DIVERSITY ANALYZER")
    print("=" * 80 + "\n")

    # Get total species count
    print("Fetching total species count...")
    total_species = analyzer.get_total_species_count(use_catalogue_of_life=not args.use_gbif_total)

    if total_species == 0:
        print("Error: Could not retrieve total species count")
        sys.exit(1)

    # Get species counts based on arguments
    counts = {}

    if args.compare:
        taxa_list = [t.strip() for t in args.compare.split(',')]
        print(f"\nAnalyzing specified taxa: {', '.join(taxa_list)}")
        counts = analyzer.get_species_counts_for_taxa(taxa_list, args.rank)

    elif args.top or args.all:
        limit = args.top if args.top else 1000
        print(f"\nFetching {'top ' + str(args.top) if args.top else 'all'} taxa at rank {args.rank}...")
        all_taxa = analyzer.get_all_taxa_at_rank(args.rank, limit)

        # Get species counts for each
        for taxon in all_taxa[:limit] if args.top else all_taxa:
            count = analyzer.get_species_count_for_taxon(taxon['name'], args.rank)
            if count is not None and count > 0:
                counts[taxon['name']] = count

        # Keep only top N if specified
        if args.top:
            sorted_counts = sorted(counts.items(), key=lambda x: x[1], reverse=True)
            counts = dict(sorted_counts[:args.top])

    if not counts:
        print("Error: No taxa data retrieved")
        sys.exit(1)

    # Generate visualizations and reports
    print("\nGenerating visualizations and reports...")

    rank_label = args.rank.title()

    # Create pie chart
    analyzer.create_pie_chart(
        counts,
        f"Distribution of Species Across {rank_label}",
        f"pie_chart_{args.rank.lower()}.png"
    )

    # Create bar chart
    analyzer.create_bar_chart(
        counts,
        f"Species Count by {rank_label}",
        f"bar_chart_{args.rank.lower()}.png",
        top_n=20  # Limit to top 20 for readability
    )

    # Create comparison chart
    analyzer.create_comparison_chart(
        counts,
        total_species,
        f"{rank_label} Diversity: Species Counts and Percentages",
        f"comparison_chart_{args.rank.lower()}.png"
    )

    # Generate statistics report
    analyzer.generate_statistics_report(
        counts,
        total_species,
        args.rank,
        f"statistics_report_{args.rank.lower()}.txt"
    )

    # Save data to CSV
    analyzer.save_data_to_csv(
        counts,
        total_species,
        f"taxa_data_{args.rank.lower()}.csv"
    )

    print("\n" + "=" * 80)
    print("ANALYSIS COMPLETE")
    print("=" * 80)
    print(f"\nAll outputs saved to: {args.output}/")
    print("\nGenerated files:")
    print(f"  - pie_chart_{args.rank.lower()}.png")
    print(f"  - bar_chart_{args.rank.lower()}.png")
    print(f"  - comparison_chart_{args.rank.lower()}.png")
    print(f"  - statistics_report_{args.rank.lower()}.txt")
    print(f"  - taxa_data_{args.rank.lower()}.csv")
    print()


if __name__ == "__main__":
    main()
