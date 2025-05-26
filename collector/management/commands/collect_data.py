import asyncio
from django.core.management.base import BaseCommand
from django.utils import timezone
from collector.fetchers import DataCollector
from collector.models import Source

class Command(BaseCommand):
    help = 'Collect data from all active sources'

    def add_arguments(self, parser):
        parser.add_argument(
            '--source-id',
            type=int,
            help='Collect from specific source ID only',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force collection regardless of fetch interval',
        )

    def handle(self, *args, **options):
        self.stdout.write('Starting data collection...')
        
        collector = DataCollector()
        
        if options['source_id']:
            # Collect from specific source
            try:
                source = Source.objects.get(id=options['source_id'], is_active=True)
                result = asyncio.run(collector.collect_from_source(source))
                self.print_result(source.source, result)
            except Source.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f'Source with ID {options["source_id"]} not found or inactive')
                )
        else:
            # Collect from all sources or only those due for update
            if not options['force']:
                # Filter sources that are due for update
                now = timezone.now()
                sources = Source.objects.filter(
                    is_active=True
                ).extra(
                    where=['last_fetched IS NULL OR (EXTRACT(EPOCH FROM %s) - EXTRACT(EPOCH FROM last_fetched)) >= fetch_interval'],
                    params=[now]
                )
                
                if not sources.exists():
                    self.stdout.write(self.style.SUCCESS('No sources due for update'))
                    return
            
            results = asyncio.run(collector.collect_all_active_sources())
            
            self.stdout.write('\n--- Collection Summary ---')
            for i, result in enumerate(results):
                if isinstance(result, dict):
                    source_name = result['source'].source
                    self.print_result(source_name, result)
        
        self.stdout.write(self.style.SUCCESS('Data collection completed'))

    def print_result(self, source_name, result):
        if result['status'] == 'success':
            self.stdout.write(
                self.style.SUCCESS(
                    f'✓ {source_name}: {result["articles_count"]} articles in {result["execution_time"]:.2f}s'
                )
            )
        else:
            self.stdout.write(
                self.style.ERROR(
                    f'✗ {source_name}: {result["error_message"]}'
                )
            )