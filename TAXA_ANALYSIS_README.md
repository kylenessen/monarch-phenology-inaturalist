# GBIF Taxa Analysis Tool

A comprehensive, general-purpose tool for querying GBIF (Global Biodiversity Information Facility) taxonomic data and generating visualizations and statistics about how different taxonomic groups represent percentages of total biodiversity.

## Features

- **Query GBIF API**: Retrieve species counts for any taxonomic group
- **Flexible Comparisons**: Compare specific taxa, analyze top N taxa, or analyze all taxa at a given rank
- **Multiple Visualizations**: Generate pie charts, bar charts, and comparison charts
- **Statistical Reports**: Detailed text reports with key findings and statistics
- **Data Export**: Save results to CSV for further analysis
- **General Purpose**: Works with any taxonomic rank (Order, Class, Phylum, Family, Kingdom)

## Installation

Install required dependencies:

```bash
pip install -r requirements.txt
```

## Usage

### Compare Specific Taxa

Compare specific orders (like Lepidoptera, Coleoptera, etc.):

```bash
python gbif_taxa_analysis.py --rank ORDER --compare Lepidoptera,Coleoptera,Diptera,Hymenoptera
```

### Analyze Top N Taxa

Analyze the top 10 orders by species count:

```bash
python gbif_taxa_analysis.py --rank ORDER --top 10
```

### Analyze All Taxa at a Rank

Analyze all classes (warning: may be slow):

```bash
python gbif_taxa_analysis.py --rank CLASS --all
```

### Custom Output Directory

Specify a custom output directory:

```bash
python gbif_taxa_analysis.py --rank ORDER --compare Lepidoptera --output lepidoptera_analysis
```

## Examples

### Example 1: Verify Lepidoptera Percentage

To verify that Lepidoptera (moths and butterflies) makes up approximately 10% of total biodiversity:

```bash
python gbif_taxa_analysis.py --rank ORDER --compare Lepidoptera
```

This will generate:
- A detailed statistics report showing the percentage
- Visualizations comparing Lepidoptera to total diversity
- CSV data for further analysis

### Example 2: Compare Major Insect Orders

```bash
python gbif_taxa_analysis.py --rank ORDER --compare Lepidoptera,Coleoptera,Diptera,Hymenoptera,Hemiptera
```

### Example 3: Analyze Top Animal Classes

```bash
python gbif_taxa_analysis.py --rank CLASS --top 15
```

## Output Files

The tool generates several output files:

1. **pie_chart_[rank].png**: Pie chart showing distribution of species
2. **bar_chart_[rank].png**: Horizontal bar chart showing species counts
3. **comparison_chart_[rank].png**: Side-by-side comparison of counts and percentages
4. **statistics_report_[rank].txt**: Detailed text report with statistics
5. **taxa_data_[rank].csv**: CSV file with all data for further analysis

## Command-Line Arguments

- `--rank`: Taxonomic rank to analyze (ORDER, CLASS, PHYLUM, FAMILY, KINGDOM)
  - Default: ORDER
- `--compare`: Comma-separated list of taxa names to compare
- `--top`: Analyze top N taxa by species count
- `--all`: Analyze all taxa at the specified rank
- `--output`: Output directory for results (default: output)

**Note**: You must specify one of `--compare`, `--top`, or `--all`.

## How It Works

1. **Query GBIF API**: The tool queries the GBIF API to retrieve species counts
2. **Match Taxa**: Each taxon name is matched to the GBIF backbone taxonomy
3. **Count Species**: Counts accepted species under each taxonomic group
4. **Calculate Percentages**: Calculates percentages relative to total described species
5. **Generate Outputs**: Creates visualizations and reports

## GBIF Data

This tool uses the GBIF Backbone Taxonomy, which is a comprehensive, continuously updated taxonomic classification. The data represents accepted species names from multiple authoritative sources.

**Note**: GBIF species counts may vary from other sources due to:
- Different taxonomic classifications
- Ongoing taxonomic revisions
- Inclusion criteria for accepted names
- Database update timing

## Lepidoptera Analysis

The tool includes special analysis for Lepidoptera (moths and butterflies), which is estimated to represent approximately 10% of all described species on Earth. The statistics report will highlight whether the GBIF data confirms this figure.

## Requirements

- Python 3.8+
- requests
- matplotlib
- pandas
- seaborn
- pygbif (optional, currently using direct API calls)

## Data Source

All taxonomic data is retrieved from:
- **GBIF API**: https://api.gbif.org/v1
- **GBIF Backbone Taxonomy**: https://www.gbif.org/dataset/d7dddbf4-2cf0-4f39-9b2a-bb099caae36c

## License

MIT License - See LICENSE file for details

## Contributing

This is part of the Monarch Phenology iNaturalist project. Contributions and suggestions are welcome.

## Citation

If you use this tool in research, please cite:

```
GBIF.org (date accessed) GBIF Backbone Taxonomy.
Checklist dataset https://doi.org/10.15468/39omei accessed via GBIF.org
```

## Troubleshooting

### API Timeouts

If you experience timeouts:
- Try analyzing fewer taxa at once
- Use `--top` with a smaller number
- The GBIF API may be temporarily slow or rate-limited

### Missing Taxa

If a taxon is not found:
- Check the spelling and capitalization
- Verify the taxon exists at the specified rank
- Some taxa may not be in the GBIF backbone taxonomy

### Large Datasets

For analyzing many taxa (--all):
- Be patient, this can take several minutes
- The tool fetches data in batches
- Consider using `--top` instead for faster results
