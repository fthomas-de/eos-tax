from eos_tax.models import MonthlyTax

    # examples: https://github.com/ppfeufer/allianceauth-afat/blob/master/afat/tasks.py   
    # tax_data = CorporationWalletJournalEntry.objects.filter(tax_receiver_id__in=corporation_info.keys(), ref_type__in=TAX_TYPES, date__year=y, date__month=m).\
    #       values('tax_receiver_id').annotate(sum=Sum('amount'))          
    #corp_id = models.IntegerField(verbose_name="Corporation ID")
    #corp_name = models.CharField(verbose_name="Corporation name", max_length=254)
    #tax_value = models.IntegerField(verbose_name="Tax value")
    #tax_percentage = models.IntegerField(verbose_name="Tax percentage")
    #month = models.IntegerField(verbose_name="Taxed month")
    #year = models.IntegerField(verbose_name="Taxed year")
def set_corp_tax(corp_id: int, corp_name: str = '', tax_value: int = -1, tax_percentage: int = -1, month: int = -1, year: int = -1):

    # exists: update
    selected_corp = MonthlyTax.objects.filter(corp_id=corp_id, month=month, year=year).first()
    
    print(tax_value)
    if selected_corp:
        print("update")
        selected_corp.corp_name=corp_name
        selected_corp.tax_value=selected_corp.tax_value+selected_corp.tax_value
        selected_corp.tax_percentage=tax_percentage

        selected_corp.save()

    else:
        print("create")
        return_value = MonthlyTax.objects.create(corp_id=corp_id, 
                                                 corp_name=corp_name,
                                                 tax_value=tax_value,
                                                 tax_percentage=tax_percentage,
                                                 month=month,
                                                 year=year)
        
        
    #print("return_value:", return_value)